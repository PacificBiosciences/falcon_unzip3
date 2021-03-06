
from falcon_kit.FastaReader import open_fasta_reader
from .. import io
import argparse
import contextlib
import os
import glob
import sys
import re
import logging
import time
global LOG
LOG = logging.getLogger()

def fetch_ref_and_reads(
        fofn, ctg_id, min_ctg_lenth,
        base_dir, p_ctg_fn, ctg_list_fn,
        ):
    ctg_fa = p_ctg_fn

    out_dir = '.'
    read_map_dir = '.'
    rawread_id_file = os.path.join(
        read_map_dir, 'dump_rawread_ids', 'rawread_ids')
    pread_id_file = os.path.join(
        read_map_dir, 'dump_pread_ids', 'pread_ids')

    rid_to_oid = open(rawread_id_file).read().split(
        '\n')  # daligner raw read id to the original ids
    pid_to_fid = open(pread_id_file).read().split(
        '\n')  # daligner pread id to the fake ids
    assert rid_to_oid, 'Empty rid_to_oid. Maybe empty {!r}?'.format(
        rawread_id_file)
    assert pid_to_fid, 'Empty pid_to_fid. Maybe empty {!r}?'.format(
        pread_id_file)

    def pid_to_oid(pid):
        fid = pid_to_fid[int(pid)]
        rid = int(fid.split('/')[1]) // 10
        return rid_to_oid[int(rid)]

    with open_fasta_reader(ctg_fa) as ref_fasta:
        all_ctg_ids = set()
        for s in ref_fasta:
            s_id = s.name.split()[0]
            if ctg_id != 'all' and s_id != ctg_id:
                continue

            if len(s.sequence) < min_ctg_lenth:
                continue

            io.mkdirs(os.path.join(out_dir, ctg_id))
            if ctg_id != 'all':
                ref_out = open(os.path.join(out_dir, ctg_id, 'ref.fasta'), 'w')
            else:
                # TODO(CD): Check when s_id != ctg_id
                io.mkdirs(os.path.join(out_dir, s_id))
                ref_out = open(os.path.join(out_dir, s_id, 'ref.fasta'), 'w')

            print('>%s' % s_id, file=ref_out)
            print(s.sequence, file=ref_out)
            all_ctg_ids.add(s_id)
            ref_out.close()

    read_set = {}
    ctg_id_hits = {}

    map_fn = os.path.join(read_map_dir, 'rawread_to_contigs')
    with open(map_fn, 'r') as f:
        for row in f:
            row = row.strip().split()
            hit_ctg = row[1]
            hit_ctg = hit_ctg.split('-')[0]
            if int(row[3]) == 0:
                o_id = rid_to_oid[int(row[0])]
                read_set[o_id] = hit_ctg
                ctg_id_hits[hit_ctg] = ctg_id_hits.get(hit_ctg, 0) + 1
    assert read_set, 'Empty read_set. Maybe empty {!}?'.format(map_fn)
    map_fn = os.path.join(read_map_dir, 'pread_to_contigs')
    with open(map_fn, 'r') as f:
        for row in f:
            row = row.strip().split()
            hit_ctg = row[1]
            hit_ctg = hit_ctg.split('-')[0]
            if int(row[3]) == 0:
                o_id = pid_to_oid(row[0])
                if o_id in read_set:
                    continue
                read_set[o_id] = hit_ctg
                ctg_id_hits[hit_ctg] = ctg_id_hits.get(hit_ctg, 0) + 1

    read_out_files = {}

    @contextlib.contextmanager
    def reopened_fasta_out(ctg_id):
        """A convenient closure, with a contextmanager."""
        io.mkdirs(os.path.join(out_dir, ctg_id))
        if ctg_id not in read_out_files:
            read_out = open(os.path.join(out_dir, ctg_id, 'reads.fasta'), 'w')
            read_out_files[ctg_id] = 1
        else:
            read_out = open(os.path.join(out_dir, ctg_id, 'reads.fasta'), 'a')
        yield read_out
        read_out.close()

    for r_fn in io.yield_abspath_from_fofn(fofn):
            # handles .fasta.gz and .dexta too
            with open_fasta_reader(r_fn) as read_fa_file:
                for r in read_fa_file:
                    rid = r.name.split()[0]
                    if rid not in read_set:
                        ctg_id = 'unassigned'
                    else:
                        ctg_id = read_set[rid]

                    if ctg_id == 'NA' or ctg_id not in all_ctg_ids:
                        ctg_id = 'unassigned'

                    with reopened_fasta_out(ctg_id) as read_out:
                        print('>' + rid, file=read_out)
                        print(r.sequence, file=read_out)

    with open(os.path.join(out_dir, ctg_list_fn), 'w') as f:
        for ctg_id in sorted(list(all_ctg_ids)):

            if ctg_id_hits.get(ctg_id, 0) < 5:
                LOG.info('Skipping contig: {}. Reason: not enough reads (ctg_id_hits.get(ctg_id, 0) = {} < 5).'.format(ctg_id, ctg_id_hits.get(ctg_id, 0)))
                continue

            # ignore small circle contigs, they need different approach
            if ctg_id[-1] not in ['F', 'R']:
                LOG.info('Skipping contig: {}. Reason: ignoring small circular contigs.'.format(ctg_id))
                continue

            reads_fa_path = os.path.join(out_dir, ctg_id, 'reads.fasta')
            if not io.check_nonempty_file_exists(reads_fa_path):
                LOG.info('Skipping contig: {}. Reason: non-existent or empty reads file ({}).'.format(ctg_id, reads_fa_path))
                continue

            ref_fa_path = os.path.join(out_dir, ctg_id, 'ref.fasta')
            if not io.check_nonempty_file_exists(ref_fa_path):
                LOG.info('Skipping contig: {}. Reason: non-existent or empty ref file ({}).'.format(ctg_id, ref_fa_path))
                continue

            print(ctg_id, file=f)

def parse_args(argv):
    description = 'Using the read to contig mapping data, to partition the reads (into {ctg_id}_reads.fasta and {ctg_id}_ref.fasta) grouped by contigs.'
    parser = argparse.ArgumentParser(description=description,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '--ctg-list-fn', type=str, default='ctg_list',
        help='Output. List of ctg_id names.')
    parser.add_argument(
        '--base-dir', type=str, default='../..',
        help='the base working dir of a falcon assembly')
    parser.add_argument(
        '--p-ctg-fn', type=str, default='{base_dir}/2-asm-falcon/p_ctg.fasta',
        help='Primary contigs of falcon assembly. (FASTA)')
    parser.add_argument(
        '--fofn', type=str, default='../../input.fofn',
        help='path to the file of the list of raw read fasta files')
    parser.add_argument(
        '--ctg-id', type=str, default='all',
        help='contig identifier in the contig fasta file')
    parser.add_argument(
        '--min-ctg-lenth', default=20000, type=int,
        help='the minimum length of the contig for the outputs')
    #parser.add_argument('--ctg_fa', type=str, default='./2-asm-falcon/p_ctg.fasta', help='path to the contig fasta file')
    # we can run this in parallel mode in the furture
    # parser.add_argument('--n_core', type=int, default=4,
    #                    help='number of processes used for generating consensus')

    args = parser.parse_args(argv[1:])
    return args


def main(argv=sys.argv):
    args = parse_args(argv)
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(
        level=logging.INFO,
        format='[INFO %(asctime)s GMT] %(message)s',
    )
    fetch_ref_and_reads(**vars(args))


if __name__ == '__main__':
    main()
