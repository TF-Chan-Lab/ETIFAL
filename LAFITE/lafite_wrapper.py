# AUTOGENERATED! DO NOT EDIT! File to edit: ../10_wrapper.ipynb.

# %% auto 0
__all__ = ['LafiteWrapper', 'main']

# %% ../10_wrapper.ipynb 2
import sys
import os
import subprocess
import argparse
import pickle

from numpy import percentile
from time import strftime

from .reference_processing import RefProcessWrapper, short_reads_sj_import, cage_tss_import, annotation_reshape, gtf2splicing, split_bed_line, bed_block_to_splicing, read_assignment
from .preprocessing import read_grouping, polya_signal_import, PolyAFinder
from .utils import temp_dir_creation, bam2bed, keep_tmp_file
from .read_collapsing import CoCoWrapper
from .tailFinder import TailFinderWrapper
from .refine import RefineWrapper
from .output import OutputAssembly

# %% ../10_wrapper.ipynb 3
class LafiteWrapper:
    def __init__(self, bam, bedtools, full_cleanup, gtf, genome, min_count_tss_tes, mis_intron_length, min_novel_trans_count,
                 min_single_exon_coverage, min_single_exon_len, label, output, polya, polyA_motif_file, relative_abundance_threshold,
                 sj_correction_window, short_sj_tab, thread, tss_cutoff, tss_peak, read_assign, assign_known):
        self.bam = bam
        self.bedtools = bedtools
        self.full_cleanup = full_cleanup
        self.gtf = gtf
        self.genome = genome
        self.min_count_tss_tes = min_count_tss_tes
        self.mis_intron_length = mis_intron_length
        self.min_novel_trans_count = min_novel_trans_count
        self.min_single_exon_coverage = min_single_exon_coverage
        self.min_single_exon_len = min_single_exon_len
        self.label = label
        self.output = output
        self.polya = polya
        self.polyA_motif_file = polyA_motif_file
        self.relative_abundance_threshold = relative_abundance_threshold
        self.sj_correction_window = sj_correction_window
        self.short_sj_tab = short_sj_tab
        self.thread = thread
        self.tss_cutoff = tss_cutoff
        self.tss_peak = tss_peak
        self.read_assign = read_assign
        self.assign_known = assign_known

    def revisit_parameter(self):
        """
        revisit input parameters"""

        sys.stdout.write(f'\nInput parameters:\n')
        sys.stdout.write(f'Read alignment file: {self.bam}\n')
        sys.stdout.write(f'Reference gene annotation: {self.gtf}\n')
        sys.stdout.write(f'Reference genome annotation: {self.genome}\n')
        if self.polya:
            sys.stdout.write(f'Reads Polyadenylation events: {self.polya}\n')
        elif self.polyA_motif_file:
            sys.stdout.write(
                f'PolyA motif file for read Polyadenylation event estimation: {self.polyA_motif_file}\n')
        else:
            raise ValueError(
                'Fatal: Please provide either polyA motif file or reads polyadenylation event result\n')
        sys.stdout.write(
            f'Edit distance to reference splicing site allowed for splicing correction: {self.sj_correction_window}\n')
        sys.stdout.write(f'Output assembly file: {self.output}\n')

    def run_lafite(self):
        """
        LAFITE wrapper"""

        self.revisit_parameter()
        # create temp directory for log and intermediate files
        try:
            tmp_folder = temp_dir_creation(os.path.dirname(self.output))
            tmp_dir = tmp_folder.name
        except:
            raise ValueError(
                'Fatal: Please provide a valid path for output files\n')

        # reference gene annotation processing
        sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") +
                         ': Preprocessing reference gene annotation\n')
        ref_exon, ref_junction, ref_single_exon_trans, ref_mutple_exon_trans, left_sj_set, right_sj_set, tss_dict = RefProcessWrapper(
            self.gtf, self.thread).result_collection()

        if self.short_sj_tab:
            left_sj_set, right_sj_set = short_reads_sj_import(
                self.short_sj_tab, left_sj_set, right_sj_set)

        if self.tss_peak:
            tss_dict = cage_tss_import(self.tss_peak, tss_dict)

        # processing alignment bam file
        # convert alignment bam file to bed12 format
        sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") +
                         ': Preprocessing alignment file\n')
        try:
            bam2bed_cmd = bam2bed(self.bam, tmp_dir, self.bedtools)
        except:
            raise ValueError(
                'Fatal: Please provide a valid path for bam file and bedtools\n')
        p = subprocess.run(bam2bed_cmd, shell=True)
        if p.returncode == 0:
            pass
        else:
            raise ValueError('Fatal: Error in bam conversion\n')

        # read grouping according to chromosome and strand
        outbed = os.path.join(tmp_dir, 'bam.bed')
        junction_dict, processed_read = read_grouping(outbed, self.genome)

        # polyA info import
        if self.polya:
            sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") +
                             ': Loading polyA information\n')
            polya_dict = polya_signal_import(self.polya)
        else:
            sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") +
                             ': No reads Polyadenylation event provided, detecting from sequence\n')
            polya_dict = PolyAFinder(
                processed_read, self.genome, self.polyA_motif_file).polya_estimation()

        # read correction and collapsing
        sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") +
                         ': Collapssing corrected reads\n')
        collected_single_exon_read, collected_multi_exon_read, collected_rss, collected_res = CoCoWrapper(
            self.thread, processed_read, ref_exon, ref_junction, ref_single_exon_trans, ref_mutple_exon_trans, left_sj_set, right_sj_set, junction_dict, self.sj_correction_window, polya_dict, self.mis_intron_length, tmp_dir).result_collection()

        # identify putative TSS and TES for collapsed reads
        processed_collected_multi_exon_read, three_prime_exon = TailFinderWrapper(
            collected_multi_exon_read, self.min_count_tss_tes, self.thread).result_collection()

        # calculating the tss_cutoff and tes_cutoff:
        if not self.tss_cutoff:
            self.tss_cutoff = percentile(collected_rss, 75)
        tes_cutoff = percentile(collected_res, 70)
        print(f'TSS cutoff: {self.tss_cutoff}')
        print(f'TES cutoff: {tes_cutoff}')

        # identify high quality isoforms from collapsed reads
        sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") +
                         ': Revisiting the collapsed reads to get high-concensus full-length isoforms\n')
        collected_refined_isoforms = RefineWrapper(processed_collected_multi_exon_read, collected_single_exon_read, ref_mutple_exon_trans, ref_single_exon_trans, three_prime_exon,
                                                   tss_dict, self.tss_cutoff, tes_cutoff, self.min_novel_trans_count, self.min_single_exon_coverage, self.min_single_exon_len, self.thread, tmp_dir).result_collection()

        # output refined isoforms
        OutputAssembly(collected_refined_isoforms, self.output,
                       self.label, self.relative_abundance_threshold).write_out()

        if self.read_assign:
            reshaped_multi_exon_isoform_dict, reshaped_single_exon_isoform_dict, single_exon_isoform_interlap = annotation_reshape(
                gtf2splicing(self.output, keepAttribute=True, no_transcript=True))
            read_assign_res = read_assignment(os.path.join(tmp_dir, 'Corrected_reads.bed'), reshaped_multi_exon_isoform_dict,
                                              reshaped_single_exon_isoform_dict, single_exon_isoform_interlap, only_known=self.assign_known)
            with open(self.output.replace('.gtf', 'read_assignment.pkl'), 'wb') as output_pkl:
                pickle.dump(read_assign_res, output_pkl)

        # keep intermediate results
        if self.full_cleanup:
            os.system(keep_tmp_file(self.output, tmp_dir))

        sys.stdout.write(strftime("%Y-%m-%d %H:%M:%S") + ': All done!\n')

# %% ../10_wrapper.ipynb 4
def main():

    parser = argparse.ArgumentParser(description='Low-abundance Aware Full-length Isoform clusTEr')
    parser.add_argument('-b', dest='bam', help='path to the alignment file in bam format', required=True)
    parser.add_argument('-B', dest='bedtools', type=str, default='bedtools', help='path to the executable bedtools')
    parser.add_argument('-g', dest='gtf', help='path to the reference gene annotation in GTF format', required=True)
    parser.add_argument('-f', dest='genome', help='path to the reference genome fasta', required=True)
    parser.add_argument('-o', dest='output', help='path to the output file', required=True)
    parser.add_argument('-n', dest='min_count_tss_tes', type=int, default=3, help='minimum number of reads supporting a alternative TSS or TES, default: 3')
    parser.add_argument('-i', dest='mis_intron_length', type=int, default=150, help='length cutoff for correcting unexpected small intron, default: 150')
    parser.add_argument('-c', dest='min_novel_trans_count', type=int, default=3, help='minimum occurrences required for a isoform from novel loci, default: 3')
    parser.add_argument('-s', dest='min_single_exon_coverage', type=int, default=4, help='minimum read coverage required for a novel single-exon transcript, default: 4')
    parser.add_argument('-l', dest='min_single_exon_len', type=int, default=100, help='minimum length for single-exon transcript, default: 100')
    parser.add_argument('-L', dest='label', type=str, default='LAFT', help='name prefix for output transcripts, default: LAFT')
    parser.add_argument('-p', dest='polya', help='path to the file contains read Polyadenylation event')
    parser.add_argument('-m', dest='polyA_motif_file', help='path to the polya motif file')
    parser.add_argument('-r', dest='relative_abundance_threshold', type=int, default=0.01, help='minimum abundance of the predicted multi-exon transcripts as a fraction of the total transcript assembled at a given locus, default: 0.01')
    parser.add_argument('-j', dest='short_sj_tab', default=None, help='path to the short read splice junction file')
    parser.add_argument('-w', dest='sj_correction_window', type=int, default=40, help='edit distance to reference splicing site for splicing correction, default: 40')
    parser.add_argument('--no_full_cleanup', dest='full_cleanup', action='store_true', help='keep all intermediate files')
    parser.add_argument('-t', dest='thread', type=int, default=4, help='number of the threads, default: 4')
    parser.add_argument('-T', dest='tss_peak', default=None, help='path to the TSS peak file')
    parser.add_argument('-d', dest='tss_cutoff', type=int, default=None, help='minimum TSS distance for a transcript to be considered as a novel transcript')
    parser.add_argument('--read-assignment', dest='read_assignment',action='store_true',help='output the read assignment')
    parser.add_argument('--assign-known', dest='assign_known',action='store_true',help='only assign reads to known transcript')
    args = parser.parse_args()

    LafiteWrapper(args.bam, args.bedtools, args.full_cleanup, args.gtf, args.genome, args.min_count_tss_tes, 
                  args.mis_intron_length, args.min_novel_trans_count, args.min_single_exon_coverage,
                  args.min_single_exon_len, args.label, args.output, args.polya, args.polyA_motif_file, args.relative_abundance_threshold, args.sj_correction_window, args.short_sj_tab, args.thread, args.tss_cutoff, 
                  args.tss_peak,args.read_assignment,args.assign_known).run_lafite()

