from falcon_kit import run_support as support
from pypeflow.simple_pwatcher_bridge import (
    PypeLocalFile, makePypeLocalFile, fn,
    PypeTask,
    PypeProcWatcherWorkflow, MyFakePypeThreadTaskBase)
from falcon_kit.FastaReader import FastaReader
from .tasks import unzip as tasks_unzip
from . import io
import glob
import logging
import os
import re
import time
import ConfigParser

LOG = logging.getLogger(__name__)


def task_track_reads(self):
    job_done = fn(self.job_done)
    fofn_fn = os.path.relpath(fn(self.fofn))
    wd = self.parameters['wd']
    #config = self.parameters['config']
    script_fn = os.path.join(wd, 'track_reads.sh')
    topdir = '../..'

    script = """\
set -vex
trap 'touch {job_done}.exit' EXIT
hostname
date

mkdir -p get_ctg_read_map
cd get_ctg_read_map
python -m falcon_unzip.mains.get_read_ctg_map --base-dir=../{topdir}
cd ..

python -m falcon_unzip.mains.rr_ctg_track --base-dir={topdir} --output=rawread_to_contigs
python -m falcon_unzip.mains.pr_ctg_track --base-dir={topdir} --output=pread_to_contigs
# Those outputs are used only by fetch_reads.
python -m falcon_unzip.mains.fetch_reads --base-dir={topdir} --fofn={fofn_fn}
date
touch {job_done}
""".format(**locals())

    with open(script_fn, 'w') as script_file:
        script_file.write(script)
    self.generated_script_fn = script_fn


def task_run_blasr(self):
    job_done = fn(self.job_done)
    ref_fasta = fn(self.ref_fasta)
    read_fasta = fn(self.read_fasta)

    job_uid = self.parameters['job_uid']
    wd = self.parameters['wd']
    ctg_id = self.parameters['ctg_id']

    config = self.parameters['config']
    smrt_bin = config['smrt_bin']
    blasr = os.path.join(smrt_bin, 'blasr')
    samtools = os.path.join(smrt_bin, 'samtools')

    script_dir = os.path.join(wd)
    script_fn = os.path.join(script_dir, 'aln_{ctg_id}.sh'.format(ctg_id=ctg_id))

    script = """\
set -vex
trap 'touch {job_done}.exit' EXIT
cd {wd}
hostname
date
cd {wd}
time {blasr} {read_fasta} {ref_fasta} --noSplitSubreads --clipping subread\
 --hitPolicy randombest --randomSeed 42 --bestn 1 --minPctIdentity 70.0\
 --minMatch 12  --nproc 24 --bam --out tmp_aln.bam
#{samtools} view -bS tmp_aln.sam | {samtools} sort - {ctg_id}_sorted
{samtools} sort tmp_aln.bam -o {ctg_id}_sorted.bam
{samtools} index {ctg_id}_sorted.bam
rm tmp_aln.bam
date
touch {job_done}
""".format(**locals())

    with open(script_fn, 'w') as script_file:
        script_file.write(script)
    self.generated_script_fn = script_fn


def task_hasm(self):
    rid_to_phase_all = fn(self.rid_to_phase_all)
    job_done = fn(self.job_done)
    #config = self.parameters['config']

    wd = self.parameters['wd']
    script_fn = os.path.join(wd, 'hasm.sh')

    las_fofn = '../../2-asm-falcon/las.fofn'
    las_fofn = '../../1-preads_ovl/merge-gather/las.fofn'
    script = """\
set -vex
trap 'touch {job_done}.exit' EXIT
hostname
date
cd {wd}

python -m falcon_unzip.mains.ovlp_filter_with_phase --fofn {las_fofn} --max_diff 120 --max_cov 120 --min_cov 1 --n_core 48 --min_len 2500 --db ../../1-preads_ovl/preads.db --rid_phase_map {rid_to_phase_all} > preads.p_ovl
python -m falcon_unzip.mains.phased_ovlp_to_graph preads.p_ovl --min_len 2500 > fc.log
if [ -e ../../1-preads_ovl/preads4falcon.fasta ];
then
  ln -sf ../../1-preads_ovl/preads4falcon.fasta .
else
  ln -sf ../../1-preads_ovl/db2falcon/preads4falcon.fasta .
fi
python -m falcon_unzip.mains.graphs_to_h_tigs --fc_asm_path ../../2-asm-falcon/ --fc_hasm_path ./ --ctg_id all --rid_phase_map {rid_to_phase_all} --fasta preads4falcon.fasta

# more script -- a little bit hacky here, we should improve

WD=$PWD
for f in `cat ../reads/ctg_list `; do mkdir -p $WD/$f; cd $WD/$f; python -m falcon_unzip.mains.dedup_h_tigs $f; done

## prepare for quviering the haplotig
cd $WD/..

find 0-phasing -name "phased_reads" | sort | xargs cat >| all_phased_reads
find 1-hasm -name "h_ctg_ids.*" | sort | xargs cat >| all_h_ctg_ids
find 1-hasm -name "p_ctg_edges.*" | sort | xargs cat >| all_p_ctg_edges
find 1-hasm -name "h_ctg_edges.*" | sort | xargs cat >| all_h_ctg_edges
find 1-hasm -name "p_ctg.*.fa" | sort | xargs cat >| all_p_ctg.fa
find 1-hasm -name "h_ctg.*.fa" | sort | xargs cat >| all_h_ctg.fa

# Generate a GFA for only primary contigs and haplotigs.
time python -m falcon_unzip.mains.unzip_gen_gfa_v1 --unzip-root $WD/.. --p-ctg-fasta $WD/../all_p_ctg.fa --h-ctg-fasta $WD/../all_h_ctg.fa --preads-fasta $WD/preads4falcon.fasta >| $WD/../asm.gfa

# Generate a GFA of all assembly graph edges. This GFA can contain
# edges and nodes which are not part of primary contigs and haplotigs
time python -m falcon_unzip.mains.unzip_gen_gfa_v1 --unzip-root $WD/.. --p-ctg-fasta $WD/../all_p_ctg.fa --h-ctg-fasta $WD/../all_h_ctg.fa --preads-fasta $WD/preads4falcon.fasta --add-string-graph >| $WD/../sg.gfa

cd ../
date
touch {job_done}
""".format(**locals())

    with open(script_fn, 'w') as script_file:
        script_file.write(script)
    self.generated_script_fn = script_fn


def task_get_rid_to_phase_all(self):
    # Tasks must be at module scope now.
    # TODO: Make this a script.
    rid_to_phase_all_fn = fn(self.rid_to_phase_all)
    inputs_fn = [fn(f) for f in self.inputs.values()]
    inputs_fn.sort()
    output = []
    LOG.info('Generate {!r} from {!r}'.format(
        rid_to_phase_all_fn, inputs_fn))
    for fname in inputs_fn:
        output.extend(open(fname).read())

    with open(rid_to_phase_all_fn, 'w') as out:
        out.write(''.join(output))


def unzip_all(config):
    unzip_blasr_concurrent_jobs = config['unzip_blasr_concurrent_jobs']
    unzip_phasing_concurrent_jobs = config['unzip_phasing_concurrent_jobs']
    wf = PypeProcWatcherWorkflow(
        max_jobs=unzip_blasr_concurrent_jobs,
        job_type=config['job_type'],
        job_queue=config.get('job_queue'),
        sge_option=config.get('sge_option'),
        watcher_type=config.get('pwatcher_type'),
        #watcher_directory=config.get('pwatcher_directory', 'mypwatcher'),
        use_tmpdir=config.get('use_tmpdir'),
    )

    ctg_list_file = makePypeLocalFile('./3-unzip/reads/ctg_list')
    falcon_asm_done = makePypeLocalFile('./2-asm-falcon/falcon_asm_done')
    fofn_file = makePypeLocalFile('./input.fofn') # TODO: Make explicit.
    wdir = os.path.abspath('./3-unzip/reads')
    parameters = {'wd': wdir, 'config': config,
                  'sge_option': config['sge_track_reads'],
                  }
    job_done = makePypeLocalFile(os.path.join(parameters['wd'], 'track_reads_done'))
    make_track_reads_task = PypeTask(
            inputs={
                'falcon_asm_done': falcon_asm_done,
                'fofn': fofn_file,
            },
            outputs={
                'job_done': job_done, 'ctg_list_file': ctg_list_file,
            },
            parameters=parameters,
            wdir=wdir,
            )
    track_reads_task = make_track_reads_task(task_track_reads)

    wf.addTask(track_reads_task)
    wf.refreshTargets()  # force refresh now, will put proper dependence later

    ctg_ids = []
    with open('./3-unzip/reads/ctg_list') as f:
        for row in f:
            row = row.strip()
            ctg_ids.append(row)

    aln1_outs = {}

    all_ctg_out = {}

    for ctg_id in ctg_ids:
        # inputs
        ref_fasta = makePypeLocalFile('./3-unzip/reads/{ctg_id}_ref.fa'.format(ctg_id=ctg_id))
        read_fasta = makePypeLocalFile('./3-unzip/reads/{ctg_id}_reads.fa'.format(ctg_id=ctg_id))

        # outputs
        wd = os.path.join(os.getcwd(), './3-unzip/0-phasing/{ctg_id}/'.format(ctg_id=ctg_id))
        # io.mkdir(wd)
        blasr_dir = os.path.join(wd, 'blasr')
        ctg_aln_out = makePypeLocalFile(os.path.join(blasr_dir, '{ctg_id}_sorted.bam'.format(ctg_id=ctg_id)))
        job_done = makePypeLocalFile(os.path.join(blasr_dir, 'aln_{ctg_id}_done'.format(ctg_id=ctg_id)))

        parameters = {'job_uid': 'aln-' + ctg_id, 'wd': blasr_dir, 'config': config, 'ctg_id': ctg_id,
                      'sge_option': config['sge_blasr_aln'],
                      }
        make_blasr_task = PypeTask(inputs={'ref_fasta': ref_fasta, 'read_fasta': read_fasta},
                                   outputs={'ctg_aln_out': ctg_aln_out, 'job_done': job_done},
                                   parameters=parameters,
                                   )
        blasr_task = make_blasr_task(task_run_blasr)
        aln1_outs[ctg_id] = (ctg_aln_out, job_done)
        wf.addTask(blasr_task)
    wf.refreshTargets()

    phasing_tasks = list(tasks_unzip.create_phasing_tasks(config, ctg_ids, all_ctg_out))
    wf.addTasks(phasing_tasks)
    wf.max_jobs = unzip_phasing_concurrent_jobs
    wf.refreshTargets()

    hasm_wd = os.path.abspath('./3-unzip/1-hasm/')
    # io.mkdir(hasm_wd)
    rid_to_phase_all = makePypeLocalFile(os.path.join(hasm_wd, 'rid-to-phase-all', 'rid_to_phase.all'))
    task = PypeTask(inputs=all_ctg_out, outputs={'rid_to_phase_all': rid_to_phase_all},
                    )(task_get_rid_to_phase_all)
    wf.addTask(task)

    parameters['wd'] = hasm_wd
    parameters['sge_option'] = config['sge_hasm']
    job_done = makePypeLocalFile(os.path.join(hasm_wd, 'hasm_done'))
    make_hasm_task = PypeTask(inputs={'rid_to_phase_all': rid_to_phase_all},
                              outputs={'job_done': job_done},
                              parameters=parameters,
                              )
    hasm_task = make_hasm_task(task_hasm)

    wf.addTask(hasm_task)

    wf.refreshTargets()


def run(config_fn):
    global LOG
    LOG = support.setup_logger(None)

    config = ConfigParser.ConfigParser()
    config.read(config_fn)

    job_type = 'SGE'
    if config.has_option('General', 'job_type'):
        job_type = config.get('General', 'job_type')

    job_queue = 'default'
    if config.has_option('General', 'job_queue'):
        job_queue = config.get('General', 'job_queue')

    pwatcher_type = 'fs_based'
    if config.has_option('General', 'pwatcher_type'):
        pwatcher_type = config.get('General', 'pwatcher_type')

    sge_blasr_aln = ' -pe smp 24 -q bigmem '
    if config.has_option('Unzip', 'sge_blasr_aln'):
        sge_blasr_aln = config.get('Unzip', 'sge_blasr_aln')

    smrt_bin = ''
    if config.has_option('Unzip', 'smrt_bin'):
        smrt_bin = config.get('Unzip', 'smrt_bin')

    sge_phasing = ' -pe smp 12 -q bigmem'
    if config.has_option('Unzip', 'sge_phasing'):
        sge_phasing = config.get('Unzip', 'sge_phasing')

    sge_hasm = ' -pe smp 48 -q bigmem'
    if config.has_option('Unzip', 'sge_hasm'):
        sge_hasm = config.get('Unzip', 'sge_hasm')

    sge_track_reads = ' -pe smp 12 -q bigmem'
    if config.has_option('Unzip', 'sge_track_reads'):
        sge_track_reads = config.get('Unzip', 'sge_track_reads')

    unzip_blasr_concurrent_jobs = 8
    if config.has_option('Unzip', 'unzip_blasr_concurrent_jobs'):
        unzip_blasr_concurrent_jobs = config.getint('Unzip', 'unzip_blasr_concurrent_jobs')

    unzip_phasing_concurrent_jobs = 8
    if config.has_option('Unzip', 'unzip_phasing_concurrent_jobs'):
        unzip_phasing_concurrent_jobs = config.getint('Unzip', 'unzip_phasing_concurrent_jobs')

    config = {'job_type': job_type,
              'job_queue': job_queue,
              'sge_blasr_aln': sge_blasr_aln,
              'smrt_bin': smrt_bin,
              'sge_phasing': sge_phasing,
              'sge_hasm': sge_hasm,
              'sge_track_reads': sge_track_reads,
              'unzip_blasr_concurrent_jobs': unzip_blasr_concurrent_jobs,
              'unzip_phasing_concurrent_jobs': unzip_phasing_concurrent_jobs,
              'pwatcher_type': pwatcher_type,
              }
    io.update_env_from_config(config, config_fn)

    # support.job_type = 'SGE' #tmp hack until we have a configuration parser

    unzip_all(config)
