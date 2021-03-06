from ..io import (serialize, log)
from .. import io


def get_rid2oid(rawread_ids_fn):
    # rid is just the line number, starting from 0.
    log("rid2oid from rawread_ids_fn:", repr(rawread_ids_fn))
    rid_to_oid = open(rawread_ids_fn).read().split('\n')
    return rid_to_oid


def get_read2ctg(rawread_ids_fn, rawread_to_contigs_fn):
    # result: read->ctg map

    read_partition = {}  # aka ctg2oids
    rid2oid = get_rid2oid(rawread_ids_fn)
    log("rawread_to_contigs_fn:", repr(rawread_to_contigs_fn))
    read2scoredctgs = {}  # read -> (score, ctg) for sorting
    with open(rawread_to_contigs_fn) as f:
        for row in f:
            row = row.strip().split()
            if int(row[3]) >= 1:  # keep top one hits
                continue
            ctg_id = row[1]
            if ctg_id == 'NA':
                continue
            read_partition.setdefault(ctg_id, set())
            r_id = row[0]
            o_id = rid2oid[int(r_id)]
            read_partition[ctg_id].add(o_id)  # TODO: See if these are non-unique.
            read2scoredctgs.setdefault(o_id, [])
            read2scoredctgs[o_id].append((int(row[4]), ctg_id))
    log("num ctgs in read_partition:", len(read_partition))
    log("num reads in read2scoredctgs:", len(read2scoredctgs))
    assert read2scoredctgs, 'Empty read2scoredctgs, from {!r}'.format(rawread_to_contigs_fn)
    assert read_partition, 'Empty read_partition, from {!r}'.format(rawread_to_contigs_fn)
    del rid2oid  # Release some memory.

    selected_ctgs = set()
    for ctg in read_partition:
        picked_reads = read_partition[ctg]
        # print "ctg, len:", ctg, len(picked_reads)
        if len(picked_reads) > 20:  # We could parameterize this someday.
            selected_ctgs.add(ctg)
    log("num selected_ctgs:", len(selected_ctgs))
    del read_partition  # Release some memory.

    # Forget reads for unselected ctgs.
    #
    # For each read, sort the scoredctgs. If the best ctg was not
    # selected, then remove this read.
    read2ctg = {}
    for read in list(read2scoredctgs.keys()):
        ctg_list = read2scoredctgs[read]
        ctg_list.sort()
        score, ctg = ctg_list[0]  # lowest (most negative?) scored ctg
        if ctg in selected_ctgs:
            read2ctg[read] = ctg
        # else: print "Not selected:", ctg

    log("num selected reads in read2ctg:", len(read2ctg))
    return read2ctg


def write_read2ctg(output, input_bam_fofn, rawread_to_contigs, rawread_ids, base_dir):
    read2ctg = get_read2ctg(rawread_ids_fn=rawread_ids, rawread_to_contigs_fn=rawread_to_contigs)
    serialize(output, read2ctg)
    serialize(output + '.json', read2ctg)


######
import argparse
import logging
import sys


def parse_args(argv):
    epilog = 'Typically run in ./4-polish/select-reads/'
    parser = argparse.ArgumentParser(
        description='Map ctg->BAM filename.',
        epilog=epilog,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '--output', type=str,
        default='./read2ctg.msgpack',
        help='Serialized map of ctg to list of BAM which contains it.')
    parser.add_argument(
        '--base-dir', type=str, default='../..',
        help='the base working dir of a falcon assembly')
    parser.add_argument(
        '--rawread-to-contigs', type=str,
        default='./{base_dir}/4-polish/track-reads/rawread_to_contigs',
        help='rawread_to_contigs file (from "fc_rr_hctg_track.py", not "fc_rr_ctg_track.py")')
    parser.add_argument(
        '--rawread-ids', type=str,
        default='./{base_dir}/3-unzip/reads/dump_rawread_ids/rawread_ids',
        help='rawread_ids file (from "fc_get_read_ctg_map.py")')
    parser.add_argument(
        'input_bam_fofn', type=str,
        help='File of BAM filenames. Paths are relative to dir of FOFN, not CWD.')
    args = parser.parse_args(argv[1:])
    return io.substitute(vars(args))


def main(argv=sys.argv):
    vargs = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(message)s',
    )
    write_read2ctg(**vargs)


if __name__ == "__main__":
    main()
