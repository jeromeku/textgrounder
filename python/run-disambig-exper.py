#!/usr/bin/env python

import os
from nlputil import *

# Run a series of disambiguation experiments.

if 'TEXTGROUNDER_PYTHON' in os.environ:
  tgdir = os.environ['TEXTGROUNDER_PYTHON']
else:
  tgdir = '%s/python' % (os.environ['TEXTGROUNDER_DIR'])

def runit(fun, id, args):
  command='%s --id %s documents %s' % (Opts.run_cmd, id, args)
  errprint("Executing: %s" % command)
  if not Opts.dry_run:
    os.system("%s" % command)

def combine(*funs):
  def do_combine(fun, *args):
    for f in funs:
      f(fun, *args)
  return do_combine

def iterate(paramname, vals):
  def do_iterate(fun, id, args):
    for val in vals:
      fun('%s.%s' % (id, val), '%s %s %s' % (args, paramname, val))
  return do_iterate

def add_param(param):
  def do_add_param(fun, id, args):
    fun(id, '%s %s' % (args, param))
  return do_add_param

def recurse(funs, *args):
  if not funs:
    return
  (funs[0])(lambda *args: recurse(funs[1:], *args), *args)

def nest(*nest_funs):
  def do_nest(fun, *args):
    recurse(nest_funs + (fun,), *args)
  return do_nest

def run_exper(exper, expername):
  exper(lambda fun, *args: runit(id, *args), expername, '')

def main():
  op = OptionParser(usage="%prog [options] experiment [...]")
  op.add_option("-n", "--dry-run", action="store_true",
		  help="Don't execute anything; just output the commands that would be executed.")
  def_runcmd = '%s/run-run-disambig' % tgdir
  op.add_option("-c", "--run-cmd", "--cmd", default=def_runcmd,
		  help="Command to execute; default '%default'.")
  (opts, args) = op.parse_args()
  global Opts
  Opts = opts
  if not args:
    op.print_help()
  for exper in args:
    run_exper(eval(exper), exper)

##############################################################################
#                       Description of experiments                           #
##############################################################################

MTS300 = iterate('--max-time-per-stage', [300])
Train200k = iterate('--num-training-docs', [200000])
Train100k = iterate('--num-training-docs', [100000])
Test2k = iterate('--num-test-docs', [2000])
Test1k = iterate('--num-test-docs', [1000])
Test500 = iterate('--num-test-docs', [500])
#CombinedNonBaselineStrategies = add_param('--strategy partial-kl-divergence --strategy cosine-similarity --strategy naive-bayes-with-baseline --strategy per-word-region-distribution')
CombinedNonBaselineStrategies = add_param('--strategy partial-kl-divergence --strategy smoothed-cosine-similarity --strategy naive-bayes-with-baseline --strategy per-word-region-distribution')
CombinedNonBaselineNoCosineStrategies = add_param('--strategy partial-kl-divergence --strategy naive-bayes-with-baseline --strategy per-word-region-distribution')
NonBaselineStrategies = iterate('--strategy',
    ['partial-kl-divergence', 'per-word-region-distribution', 'naive-bayes-with-baseline', 'smoothed-cosine-similarity'])
BaselineStrategies = iterate('--strategy baseline --baseline-strategy',
    ['link-most-common-toponym', 'regdist-most-common-toponym',
    'internal-link', 'num-articles', 'random'])
CombinedBaselineStrategies1 = add_param('--strategy baseline --baseline-strategy link-most-common-toponym --baseline-strategy regdist-most-common-toponym')
CombinedBaselineStrategies2 = add_param('--strategy baseline --baseline-strategy internal-link --baseline-strategy num-articles --baseline-strategy random')
CombinedBaselineStrategies = combine(CombinedBaselineStrategies1, CombinedBaselineStrategies2)
AllStrategies = combine(NonBaselineStrategies, BaselineStrategies)
CombinedKL = add_param('--strategy symmetric-partial-kl-divergence --strategy symmetric-kl-divergence --strategy partial-kl-divergence --strategy kl-divergence')
CombinedCosine = add_param('--strategy cosine-similarity --strategy smoothed-cosine-similarity --strategy partial-cosine-similarity --strategy smoothed-partial-cosine-similarity')
KLDivStrategy = iterate('--strategy', ['partial-kl-divergence'])
FullKLDivStrategy = iterate('--strategy', ['kl-divergence'])
SmoothedCosineStrategy = iterate('--strategy', ['smoothed-cosine-similarity'])
NBStrategy = iterate('--strategy', ['naive-bayes-no-baseline'])

Coarser1DPR = iterate('--degrees-per-region', [0.1, 10])
Coarser2DPR = iterate('--degrees-per-region', [0.5, 1, 5])
CoarseDPR = iterate('--degrees-per-region',
    #[90, 30, 10, 5, 3, 2, 1, 0.5]
    #[0.5, 1, 2, 3, 5, 10, 30, 90]
    [0.5, 1, 2, 3, 5, 10])
OldFineDPR = iterate('--degrees-per-region',
    [90, 75, 60, 50, 40, 30, 25, 20, 15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2.5, 2,
     1.75, 1.5, 1.25, 1, 0.87, 0.75, 0.63, 0.5, 0.4, 0.3, 0.25, 0.2, 0.15, 0.1]
    )
DPRList1 = iterate('--degrees-per-region', [0.5, 1, 3])

DPR3 = iterate('--degrees-per-region', [3])
DPR7 = iterate('--degrees-per-region', [7])
DPR5 = iterate('--degrees-per-region', [5])
DPR10 = iterate('--degrees-per-region', [10])
DPR1 = iterate('--degrees-per-region', [1])
DPRpoint5 = iterate('--degrees-per-region', [0.5])
DPRpoint1 = iterate('--degrees-per-region', [0.1])

MinWordCount = iterate('--minimum-word-count', [1, 2, 3, 4, 5])

CoarseDisambig = nest(MTS300, AllStrategies, CoarseDPR)

# PCL experiments
PCLDPR = iterate('--degrees-per-region', [1.5, 0.5, 1, 2, 3, 5])
corpora_dir = os.getenv('CORPORA_DIR') or '/groups/corpora'
PCLEvalFile = add_param('-f pcl-travel -e %s/pcl_travel/books' % corpora_dir)
PCLDisambig = nest(MTS300, PCLEvalFile, NonBaselineStrategies, PCLDPR)

# Param experiments

ParamExper = nest(MTS300, DPRList1, MinWordCount, NonBaselineStrategies)

# Fine experiments

FinerDPR = iterate('--degrees-per-region', [0.3, 0.2, 0.1])
EvenFinerDPR = iterate('--degrees-per-region', [0.1, 0.05])
Finer3DPR = iterate('--degrees-per-region', [0.01, 0.05])
FinerExper = nest(MTS300, FinerDPR, KLDivStrategy)
EvenFinerExper = nest(MTS300, EvenFinerDPR, KLDivStrategy)

# Missing experiments

MissingNonBaselineStrategies = iterate('--strategy',
    ['naive-bayes-no-baseline', 'partial-cosine-similarity', 'cosine-similarity'])
MissingBaselineStrategies = iterate('--strategy baseline --baseline-strategy',
    ['link-most-common-toponym'
      #, 'regdist-most-common-toponym'
      ])
MissingOtherNonBaselineStrategies = iterate('--strategy',
    ['partial-cosine-similarity', 'cosine-similarity'])
MissingAllButNBStrategies = combine(MissingOtherNonBaselineStrategies,
    MissingBaselineStrategies)
#Original MissingExper failed on or didn't include all but
#regdist-most-common-toponym.
#MissingExper = nest(MTS300, CoarseDPR, MissingAllStrategies)

MissingNBExper = nest(MTS300, CoarseDPR, NBStrategy)
MissingOtherExper = nest(MTS300, CoarseDPR, MissingAllButNBStrategies)
MissingBaselineExper = nest(MTS300, CoarseDPR, MissingBaselineStrategies)
FullKLDivExper = nest(MTS300, CoarseDPR, FullKLDivStrategy)

# Newer experiments on 200k/1k

#CombinedKLExper = nest(Train100k, Test1k, DPR5, CombinedKL)
#CombinedCosineExper = nest(Train100k, Test1k, DPR5, CombinedCosine)
CombinedKLExper = nest(Train100k, Test500, DPR5, CombinedKL)
CombinedCosineExper = nest(Train100k, Test500, DPR5, CombinedCosine)

NewCoarser1Exper = nest(Train100k, Test500, Coarser1DPR, CombinedNonBaselineStrategies)
NewCoarser2Exper = nest(Train100k, Test500, Coarser2DPR, CombinedNonBaselineStrategies)
NewFiner3Exper = nest(Train100k, Test500, Finer3DPR, KLDivStrategy)
NewIndiv4Exper = nest(Train100k, Test500, DPRpoint5, CombinedNonBaselineNoCosineStrategies)
NewIndiv5Exper = nest(Train100k, Test500, DPRpoint5, CombinedBaselineStrategies1)

NewDPR = iterate('--degrees-per-region', [0.1, 0.5, 1, 5])
NewDPR2 = iterate('--degrees-per-region', [0.1, 0.5, 1, 5, 10])
New10DPR = iterate('--degrees-per-region', [10])
New510DPR = iterate('--degrees-per-region', [5, 10])
New1DPR = iterate('--degrees-per-region', [1])
NewSmoothedCosineExper = nest(Train100k, Test500, SmoothedCosineStrategy, NewDPR)
NewSmoothedCosineExper2 = nest(Train100k, Test500, SmoothedCosineStrategy, New10DPR)
New10Exper = nest(Train100k, Test500, New10DPR, CombinedNonBaselineStrategies)
NewBaselineExper = nest(Train100k, Test500, NewDPR2, CombinedBaselineStrategies)
NewBaseline2Exper1 = nest(Train100k, Test500, New1DPR, CombinedBaselineStrategies2)
NewBaseline2Exper2 = nest(Train100k, Test500, New510DPR, CombinedBaselineStrategies)

# Final experiments performed prior to original submission, c. Dec 17 2010

TestDPR = iterate('--degrees-per-region', [0.1])
TestSet = add_param('--eval-set test')
TestStrat1 = iterate('--strategy', ['partial-kl-divergence'])
TestStrat2 = iterate('--strategy', ['per-word-region-distribution'])
TestStrat3 = iterate('--strategy', ['naive-bayes-with-baseline'])
Test2Sec1 = add_param('--skip-initial 31 --skip-n 2')
Test2Sec2 = add_param('--skip-initial 32 --skip-n 2')
Test2Sec3 = add_param('--skip-initial 33 --skip-n 5')
Test2Sec4 = add_param('--skip-initial 36 --skip-n 5')
TestExper1 = nest(Train100k, Test1k, TestSet, TestDPR, TestStrat1)
TestExper2 = nest(Train100k, Test1k, TestSet, TestDPR, TestStrat2)
TestExper2Sec1 = nest(Train100k, Test1k, TestSet, TestDPR, TestStrat2, Test2Sec1)
TestExper2Sec2 = nest(Train100k, Test1k, TestSet, TestDPR, TestStrat2, Test2Sec2)
TestExper2Sec3 = nest(Train100k, Test1k, TestSet, TestDPR, TestStrat2, Test2Sec3)
TestExper2Sec4 = nest(Train100k, Test1k, TestSet, TestDPR, TestStrat2, Test2Sec4)
TestExper3 = nest(Train100k, Test1k, TestSet, TestDPR, TestStrat3)

TestStratBase1 = add_param('--strategy baseline --baseline-strategy link-most-common-toponym --baseline-strategy regdist-most-common-toponym')
TestStratBase2 = add_param('--strategy baseline --baseline-strategy num-articles --baseline-strategy random')
TestExperBase1 = nest(Train100k, Test1k, TestSet, TestDPR, TestStratBase1)
TestExperBase2 = nest(Train100k, Test500, TestSet, TestDPR, TestStratBase2)

# Final experiments performed prior to final submission, c. Apr 10-15 2011
WikiFinalKL = nest(Test2k, TestSet, TestDPR, TestStrat1)

WikiFinal1 = nest(TestSet, TestDPR, TestStrat1)
WikiFinal2 = nest(TestSet, TestDPR, TestStrat2)
WikiFinal3 = nest(TestSet, TestDPR, TestStrat3)

Final1Sec1 = add_param('--skip-initial 0 --skip-n 5')
Final1Sec2 = add_param('--skip-initial 1 --skip-n 5')
Final1Sec3 = add_param('--skip-initial 2 --skip-n 5')
Final1Sec4 = add_param('--skip-initial 3 --skip-n 5')
Final1Sec5 = add_param('--skip-initial 4 --skip-n 5')
Final1Sec6 = add_param('--skip-initial 5 --skip-n 5')

WikiFinal1Sec1 = nest(TestSet, TestDPR, TestStrat1, Final1Sec1)
WikiFinal1Sec2 = nest(TestSet, TestDPR, TestStrat1, Final1Sec2)
WikiFinal1Sec3 = nest(TestSet, TestDPR, TestStrat1, Final1Sec3)
WikiFinal1Sec4 = nest(TestSet, TestDPR, TestStrat1, Final1Sec4)
WikiFinal1Sec5 = nest(TestSet, TestDPR, TestStrat1, Final1Sec5)
WikiFinal1Sec6 = nest(TestSet, TestDPR, TestStrat1, Final1Sec6)

Final1Sec7 = add_param('--skip-initial 33786 --skip-n 5')
Final1Sec8 = add_param('--skip-initial 34453 --skip-n 5')
Final1Sec9 = add_param('--skip-initial 33272 --skip-n 5')
Final1Sec10 = add_param('--skip-initial 35121 --skip-n 5')
Final1Sec11 = add_param('--skip-initial 33796 --skip-n 5')
Final1Sec12 = add_param('--skip-initial 35363 --skip-n 5')

WikiFinal1Sec7 = nest(TestSet, TestDPR, TestStrat1, Final1Sec7)
WikiFinal1Sec8 = nest(TestSet, TestDPR, TestStrat1, Final1Sec8)
WikiFinal1Sec9 = nest(TestSet, TestDPR, TestStrat1, Final1Sec9)
WikiFinal1Sec10 = nest(TestSet, TestDPR, TestStrat1, Final1Sec10)
WikiFinal1Sec11 = nest(TestSet, TestDPR, TestStrat1, Final1Sec11)
WikiFinal1Sec12 = nest(TestSet, TestDPR, TestStrat1, Final1Sec12)

# Experiments to test memory usage and speed with different sizes of LRU
# cache.
TestLRU150 = iterate('--lru', ['150'])
TestLRU200 = iterate('--lru', ['200'])
TestLRU300 = iterate('--lru', ['300'])
TestLRU350 = iterate('--lru', ['350'])
TestLRU400 = iterate('--lru', ['400'])
TestLRU500 = iterate('--lru', ['500'])
TestLRU600 = iterate('--lru', ['600'])
TestLRU700 = iterate('--lru', ['700'])
TestLRU1200 = iterate('--lru', ['1200'])
TestLRU4000 = iterate('--lru', ['4000'])

WikiFinal2LRU400 = nest(TestSet, TestDPR, TestStrat2, TestLRU400)
WikiFinal2LRU1200 = nest(TestSet, TestDPR, TestStrat2, TestLRU1200)
WikiFinal2LRU4000 = nest(TestSet, TestDPR, TestStrat2, TestLRU4000)

TestSkip59 = add_param('--skip-n 59')
TestSkip31 = add_param('--skip-n 31')

TestOffset0 = iterate('--skip-initial', ['0'])
TestOffset1 = iterate('--skip-initial', ['1'])
TestOffset2 = iterate('--skip-initial', ['2'])
TestOffset3 = iterate('--skip-initial', ['3'])
TestOffset4 = iterate('--skip-initial', ['4'])
TestOffset5 = iterate('--skip-initial', ['5'])
TestOffset6 = iterate('--skip-initial', ['6'])
TestOffset7 = iterate('--skip-initial', ['7'])
TestOffset8 = iterate('--skip-initial', ['8'])
TestOffset9 = iterate('--skip-initial', ['9'])
TestOffset10 = iterate('--skip-initial', ['10'])
TestOffset11 = iterate('--skip-initial', ['11'])
TestOffset12 = iterate('--skip-initial', ['12'])
TestOffset13 = iterate('--skip-initial', ['13'])
TestOffset14 = iterate('--skip-initial', ['14'])
TestOffset15 = iterate('--skip-initial', ['15'])
TestOffset16 = iterate('--skip-initial', ['16'])
TestOffset17 = iterate('--skip-initial', ['17'])
TestOffset18 = iterate('--skip-initial', ['18'])
TestOffset19 = iterate('--skip-initial', ['19'])
TestOffset20 = iterate('--skip-initial', ['20'])
TestOffset21 = iterate('--skip-initial', ['21'])
TestOffset22 = iterate('--skip-initial', ['22'])
TestOffset23 = iterate('--skip-initial', ['23'])
TestOffset24 = iterate('--skip-initial', ['24'])
TestOffset25 = iterate('--skip-initial', ['25'])
TestOffset26 = iterate('--skip-initial', ['26'])
TestOffset27 = iterate('--skip-initial', ['27'])
TestOffset28 = iterate('--skip-initial', ['28'])
TestOffset29 = iterate('--skip-initial', ['29'])
TestOffset30 = iterate('--skip-initial', ['30'])
TestOffset31 = iterate('--skip-initial', ['31'])
TestOffset32 = iterate('--skip-initial', ['32'])
TestOffset33 = iterate('--skip-initial', ['33'])
TestOffset34 = iterate('--skip-initial', ['34'])
TestOffset35 = iterate('--skip-initial', ['35'])
TestOffset36 = iterate('--skip-initial', ['36'])
TestOffset37 = iterate('--skip-initial', ['37'])
TestOffset38 = iterate('--skip-initial', ['38'])
TestOffset39 = iterate('--skip-initial', ['39'])
TestOffset40 = iterate('--skip-initial', ['40'])
TestOffset41 = iterate('--skip-initial', ['41'])
TestOffset42 = iterate('--skip-initial', ['42'])
TestOffset43 = iterate('--skip-initial', ['43'])
TestOffset44 = iterate('--skip-initial', ['44'])
TestOffset45 = iterate('--skip-initial', ['45'])
TestOffset46 = iterate('--skip-initial', ['46'])
TestOffset47 = iterate('--skip-initial', ['47'])
TestOffset48 = iterate('--skip-initial', ['48'])
TestOffset49 = iterate('--skip-initial', ['49'])
TestOffset50 = iterate('--skip-initial', ['50'])
TestOffset51 = iterate('--skip-initial', ['51'])
TestOffset52 = iterate('--skip-initial', ['52'])
TestOffset53 = iterate('--skip-initial', ['53'])
TestOffset54 = iterate('--skip-initial', ['54'])
TestOffset55 = iterate('--skip-initial', ['55'])
TestOffset56 = iterate('--skip-initial', ['56'])
TestOffset57 = iterate('--skip-initial', ['57'])
TestOffset58 = iterate('--skip-initial', ['58'])
TestOffset59 = iterate('--skip-initial', ['59'])

WikiFinal2Sec0 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset0)
WikiFinal2Sec1 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset1)
WikiFinal2Sec2 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset2)
WikiFinal2Sec3 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset3)
WikiFinal2Sec4 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset4)
WikiFinal2Sec5 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset5)
WikiFinal2Sec6 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset6)
WikiFinal2Sec7 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset7)
WikiFinal2Sec8 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset8)
WikiFinal2Sec9 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset9)
WikiFinal2Sec10 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset10)
WikiFinal2Sec11 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset11)
WikiFinal2Sec12 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset12)
WikiFinal2Sec13 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset13)
WikiFinal2Sec14 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset14)
WikiFinal2Sec15 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset15)
WikiFinal2Sec16 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset16)
WikiFinal2Sec17 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset17)
WikiFinal2Sec18 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset18)
WikiFinal2Sec19 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset19)
WikiFinal2Sec20 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset20)
WikiFinal2Sec21 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset21)
WikiFinal2Sec22 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset22)
WikiFinal2Sec23 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset23)
WikiFinal2Sec24 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset24)
WikiFinal2Sec25 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset25)
WikiFinal2Sec26 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset26)
WikiFinal2Sec27 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset27)
WikiFinal2Sec28 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset28)
WikiFinal2Sec29 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset29)
WikiFinal2Sec30 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset30)
WikiFinal2Sec31 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset31)
WikiFinal2Sec32 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset32)
WikiFinal2Sec33 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset33)
WikiFinal2Sec34 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset34)
WikiFinal2Sec35 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU500, TestOffset35)
WikiFinal2Sec36 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset36)
WikiFinal2Sec37 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset37)
WikiFinal2Sec38 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset38)
WikiFinal2Sec39 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset39)
WikiFinal2Sec40 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset40)
WikiFinal2Sec41 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset41)
WikiFinal2Sec42 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset42)
WikiFinal2Sec43 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset43)
WikiFinal2Sec44 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset44)
WikiFinal2Sec45 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset45)
WikiFinal2Sec46 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset46)
WikiFinal2Sec47 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset47)
WikiFinal2Sec48 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset48)
WikiFinal2Sec49 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset49)
WikiFinal2Sec50 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset50)
WikiFinal2Sec51 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset51)
WikiFinal2Sec52 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset52)
WikiFinal2Sec53 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset53)
WikiFinal2Sec54 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset54)
WikiFinal2Sec55 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset55)
WikiFinal2Sec56 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset56)
WikiFinal2Sec57 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset57)
WikiFinal2Sec58 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset58)
WikiFinal2Sec59 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset59)

TestOffset2a0= iterate('--skip-initial', ['46201'])
TestOffset2a1= iterate('--skip-initial', ['45312'])
TestOffset2a2= iterate('--skip-initial', ['48496'])
TestOffset2a3= iterate('--skip-initial', ['48258'])
TestOffset2a4= iterate('--skip-initial', ['47359'])
TestOffset2a5= iterate('--skip-initial', ['46404'])
TestOffset2a6= iterate('--skip-initial', ['48386'])
TestOffset2a7= iterate('--skip-initial', ['47127'])
TestOffset2a8= iterate('--skip-initial', ['46588'])
TestOffset2a9= iterate('--skip-initial', ['46953'])
TestOffset2a10= iterate('--skip-initial', ['47104'])
TestOffset2a11= iterate('--skip-initial', ['44466'])
TestOffset2a12= iterate('--skip-initial', ['43927'])

TestOffset2b0= iterate('--skip-initial', ['48000'])
TestOffset2b1= iterate('--skip-initial', ['47300'])
TestOffset2b2= iterate('--skip-initial', ['46600'])
TestOffset2b3= iterate('--skip-initial', ['45900'])
TestOffset2b4= iterate('--skip-initial', ['45200'])
TestOffset2b5= iterate('--skip-initial', ['44500'])
TestOffset2b6= iterate('--skip-initial', ['43800'])

WikiFinal2aSec0 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU150, TestOffset2a0)
WikiFinal2aSec1 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU150, TestOffset2a1)
WikiFinal2aSec2 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset2a2)
WikiFinal2aSec3 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset2a3)
WikiFinal2aSec4 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset2a4)
WikiFinal2aSec5 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU150, TestOffset2a5)
WikiFinal2aSec6 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset2a6)
WikiFinal2aSec7 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset2a7)
WikiFinal2aSec8 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU150, TestOffset2a8)
WikiFinal2aSec9 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU150, TestOffset2a9)
WikiFinal2aSec10 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset2a10)
WikiFinal2aSec11 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU700, TestOffset2a11)
WikiFinal2aSec12 = nest(TestSet, TestDPR, TestStrat2, TestSkip59, TestLRU150, TestOffset2a12)

WikiFinal2bSec0 = nest(TestSet, TestDPR, TestStrat2, TestLRU700, TestOffset2b0)
WikiFinal2bSec1 = nest(TestSet, TestDPR, TestStrat2, TestLRU700, TestOffset2b1)
WikiFinal2bSec2 = nest(TestSet, TestDPR, TestStrat2, TestLRU700, TestOffset2b2)
WikiFinal2bSec3 = nest(TestSet, TestDPR, TestStrat2, TestLRU700, TestOffset2b3)
WikiFinal2bSec4 = nest(TestSet, TestDPR, TestStrat2, TestLRU700, TestOffset2b4)
WikiFinal2bSec5 = nest(TestSet, TestDPR, TestStrat2, TestLRU700, TestOffset2b5)
WikiFinal2bSec6 = nest(TestSet, TestDPR, TestStrat2, TestLRU700, TestOffset2b6)



WikiFinal3Sec0 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset0)
WikiFinal3Sec1 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset1)
WikiFinal3Sec2 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset2)
WikiFinal3Sec3 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset3)
WikiFinal3Sec4 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset4)
WikiFinal3Sec5 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset5)
WikiFinal3Sec6 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset6)
WikiFinal3Sec7 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset7)
WikiFinal3Sec8 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset8)
WikiFinal3Sec9 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset9)
WikiFinal3Sec10 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset10)
WikiFinal3Sec11 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset11)
WikiFinal3Sec12 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset12)
WikiFinal3Sec13 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset13)
WikiFinal3Sec14 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset14)
WikiFinal3Sec15 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset15)
WikiFinal3Sec16 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset16)
WikiFinal3Sec17 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset17)
WikiFinal3Sec18 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset18)
WikiFinal3Sec19 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset19)
WikiFinal3Sec20 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset20)
WikiFinal3Sec21 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset21)
WikiFinal3Sec22 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset22)
WikiFinal3Sec23 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset23)
WikiFinal3Sec24 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset24)
WikiFinal3Sec25 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset25)
WikiFinal3Sec26 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset26)
WikiFinal3Sec27 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset27)
WikiFinal3Sec28 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset28)
WikiFinal3Sec29 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset29)
WikiFinal3Sec30 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset30)
WikiFinal3Sec31 = nest(TestSet, TestDPR, TestStrat3, TestSkip31, TestOffset31)


TestFinalStratBase1 = add_param('--strategy baseline --baseline-strategy link-most-common-toponym')
TestFinalStratBase2 = add_param('--strategy baseline --baseline-strategy regdist-most-common-toponym')
TestFinalStratBase3 = add_param('--strategy baseline --baseline-strategy num-articles')
TestFinalStratBase4 = add_param('--strategy baseline --baseline-strategy random')

WikiFinalBase1 = nest(TestSet, TestDPR, TestFinalStratBase1)
FinalBase1aSkip = add_param('--skip-initial 46916')
WikiFinalBase1a = nest(TestSet, TestDPR, TestFinalStratBase1, FinalBase1aSkip)
WikiFinalBase2 = nest(TestSet, TestDPR, TestFinalStratBase2)
WikiFinalBase3 = nest(TestSet, TestDPR, TestFinalStratBase3)
WikiFinalBase4 = nest(TestSet, TestDPR, TestFinalStratBase4)

FinalBase2aSkip = add_param('--skip-initial 40105')
WikiFinalBase2a = nest(TestSet, TestDPR, TestFinalStratBase2, FinalBase2aSkip)

TwitterDPR1 = iterate('--degrees-per-region', [0.5, 1, 0.1, 5, 10])
TwitterExper1 = nest(TwitterDPR1, KLDivStrategy)
TwitterDPR2 = iterate('--degrees-per-region', [1, 5, 10, 0.5, 0.1])
TwitterStrategy2 = add_param('--strategy naive-bayes-with-baseline --strategy smoothed-cosine-similarity --strategy per-word-region-distribution')
TwitterExper2 = nest(TwitterDPR2, TwitterStrategy2)
TwitterDPR3 = iterate('--degrees-per-region', [5, 10, 1, 0.5, 0.1])
TwitterStrategy3 = add_param('--strategy cosine-similarity')
TwitterExper3 = nest(TwitterDPR3, TwitterStrategy3)
TwitterBaselineExper1 = nest(TwitterDPR3, BaselineStrategies)
TwitterAllThresh1 = iterate('--doc-thresh', [40, 5, 0, 20, 10, 3, 2])
TwitterAllThresh2 = iterate('--doc-thresh', [20, 10, 3, 2])
TwitterAllThresh2 = iterate('--doc-thresh', [5, 10, 3, 2])
TwitterDevSet = add_param('--eval-set dev')
TwitterTestSet = add_param('--eval-set test')

Thresh2 = iterate('--doc-thresh', [2])
Thresh3 = iterate('--doc-thresh', [3])
Thresh5 = iterate('--doc-thresh', [5])
Thresh10 = iterate('--doc-thresh', [10])
Thresh20 = iterate('--doc-thresh', [20])
Thresh40 = iterate('--doc-thresh', [40])

#TwitterAllThreshExper1 = nest(TwitterAllThresh1, TwitterExper1)
TwitterAllThreshExper1 = nest(TwitterAllThresh1, TwitterDPR1, KLDivStrategy)
TwitterDPR5 = iterate('--degrees-per-region', [5])
TwitterAllThreshExper2 = nest(TwitterAllThresh2, TwitterDPR5, KLDivStrategy)
TwitterAllThreshExper3 = nest(TwitterAllThresh2, TwitterDPR1, KLDivStrategy)

TwitterDevStrat2Thresh10DPR1 =      nest(Thresh10, DPR1, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh10DPR5 =      nest(Thresh10, DPR5, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh10DPR10 =     nest(Thresh10, DPR10, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh10DPRpoint1 = nest(Thresh10, DPRpoint1, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh10DPRpoint5 = nest(Thresh10, DPRpoint5, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh5DPR1 =      nest(Thresh5, DPR1, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh5DPR5 =      nest(Thresh5, DPR5, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh5DPR10 =     nest(Thresh5, DPR10, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh5DPRpoint1 = nest(Thresh5, DPRpoint1, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh5DPRpoint5 = nest(Thresh5, DPRpoint5, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh2DPR1 =      nest(Thresh2, DPR1, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh2DPR5 =      nest(Thresh2, DPR5, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh2DPR10 =     nest(Thresh2, DPR10, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh2DPRpoint1 = nest(Thresh2, DPRpoint1, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh2DPRpoint5 = nest(Thresh2, DPRpoint5, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh3DPR1 =      nest(Thresh3, DPR1, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh3DPR5 =      nest(Thresh3, DPR5, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh3DPR10 =     nest(Thresh3, DPR10, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh3DPRpoint1 = nest(Thresh3, DPRpoint1, TestStrat2, TwitterDevSet)
TwitterDevStrat2Thresh3DPRpoint5 = nest(Thresh3, DPRpoint5, TestStrat2, TwitterDevSet)

TwitterDevStrat3Thresh10DPR1 =      nest(Thresh10, DPR1, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh10DPR5 =      nest(Thresh10, DPR5, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh10DPR10 =     nest(Thresh10, DPR10, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh10DPRpoint1 = nest(Thresh10, DPRpoint1, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh10DPRpoint5 = nest(Thresh10, DPRpoint5, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh5DPR1 =      nest(Thresh5, DPR1, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh5DPR5 =      nest(Thresh5, DPR5, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh5DPR10 =     nest(Thresh5, DPR10, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh5DPRpoint1 = nest(Thresh5, DPRpoint1, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh5DPRpoint5 = nest(Thresh5, DPRpoint5, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh2DPR1 =      nest(Thresh2, DPR1, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh2DPR5 =      nest(Thresh2, DPR5, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh2DPR10 =     nest(Thresh2, DPR10, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh2DPRpoint1 = nest(Thresh2, DPRpoint1, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh2DPRpoint5 = nest(Thresh2, DPRpoint5, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh3DPR1 =      nest(Thresh3, DPR1, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh3DPR5 =      nest(Thresh3, DPR5, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh3DPR10 =     nest(Thresh3, DPR10, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh3DPRpoint1 = nest(Thresh3, DPRpoint1, TestStrat3, TwitterDevSet)
TwitterDevStrat3Thresh3DPRpoint5 = nest(Thresh3, DPRpoint5, TestStrat3, TwitterDevSet)

TwitterDevStratBase1Thresh10DPR1 =      nest(Thresh10, DPR1, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh10DPR5 =      nest(Thresh10, DPR5, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh10DPR10 =     nest(Thresh10, DPR10, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh10DPRpoint1 = nest(Thresh10, DPRpoint1, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh10DPRpoint5 = nest(Thresh10, DPRpoint5, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh5DPR1 =      nest(Thresh5, DPR1, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh5DPR5 =      nest(Thresh5, DPR5, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh5DPR10 =     nest(Thresh5, DPR10, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh5DPRpoint1 = nest(Thresh5, DPRpoint1, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh5DPRpoint5 = nest(Thresh5, DPRpoint5, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh2DPR1 =      nest(Thresh2, DPR1, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh2DPR5 =      nest(Thresh2, DPR5, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh2DPR10 =     nest(Thresh2, DPR10, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh2DPRpoint1 = nest(Thresh2, DPRpoint1, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh2DPRpoint5 = nest(Thresh2, DPRpoint5, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh3DPR1 =      nest(Thresh3, DPR1, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh3DPR5 =      nest(Thresh3, DPR5, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh3DPR10 =     nest(Thresh3, DPR10, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh3DPRpoint1 = nest(Thresh3, DPRpoint1, TestFinalStratBase1, TwitterDevSet)
TwitterDevStratBase1Thresh3DPRpoint5 = nest(Thresh3, DPRpoint5, TestFinalStratBase1, TwitterDevSet)

TwitterDevStratBase2Thresh10DPR1 =      nest(Thresh10, DPR1, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh10DPR5 =      nest(Thresh10, DPR5, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh10DPR10 =     nest(Thresh10, DPR10, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh10DPRpoint1 = nest(Thresh10, DPRpoint1, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh10DPRpoint5 = nest(Thresh10, DPRpoint5, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh5DPR1 =      nest(Thresh5, DPR1, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh5DPR5 =      nest(Thresh5, DPR5, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh5DPR10 =     nest(Thresh5, DPR10, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh5DPRpoint1 = nest(Thresh5, DPRpoint1, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh5DPRpoint5 = nest(Thresh5, DPRpoint5, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh2DPR1 =      nest(Thresh2, DPR1, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh2DPR5 =      nest(Thresh2, DPR5, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh2DPR10 =     nest(Thresh2, DPR10, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh2DPRpoint1 = nest(Thresh2, DPRpoint1, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh2DPRpoint5 = nest(Thresh2, DPRpoint5, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh3DPR1 =      nest(Thresh3, DPR1, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh3DPR5 =      nest(Thresh3, DPR5, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh3DPR10 =     nest(Thresh3, DPR10, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh3DPRpoint1 = nest(Thresh3, DPRpoint1, TestFinalStratBase2, TwitterDevSet)
TwitterDevStratBase2Thresh3DPRpoint5 = nest(Thresh3, DPRpoint5, TestFinalStratBase2, TwitterDevSet)

TwitterDevStratBase4Thresh10DPR1 =      nest(Thresh10, DPR1, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh10DPR5 =      nest(Thresh10, DPR5, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh10DPR10 =     nest(Thresh10, DPR10, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh10DPRpoint1 = nest(Thresh10, DPRpoint1, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh10DPRpoint5 = nest(Thresh10, DPRpoint5, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh5DPR1 =      nest(Thresh5, DPR1, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh5DPR5 =      nest(Thresh5, DPR5, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh5DPR10 =     nest(Thresh5, DPR10, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh5DPRpoint1 = nest(Thresh5, DPRpoint1, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh5DPRpoint5 = nest(Thresh5, DPRpoint5, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh2DPR1 =      nest(Thresh2, DPR1, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh2DPR5 =      nest(Thresh2, DPR5, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh2DPR10 =     nest(Thresh2, DPR10, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh2DPRpoint1 = nest(Thresh2, DPRpoint1, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh2DPRpoint5 = nest(Thresh2, DPRpoint5, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh3DPR1 =      nest(Thresh3, DPR1, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh3DPR5 =      nest(Thresh3, DPR5, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh3DPR10 =     nest(Thresh3, DPR10, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh3DPRpoint1 = nest(Thresh3, DPRpoint1, TestFinalStratBase4, TwitterDevSet)
TwitterDevStratBase4Thresh3DPRpoint5 = nest(Thresh3, DPRpoint5, TestFinalStratBase4, TwitterDevSet)

TwitterDevStrategy1 = add_param('--strategy partial-kl-divergence --strategy naive-bayes-with-baseline --strategy per-word-region-distribution')
#TwitterDevStrategy2 = add_param('--strategy baseline --baseline-strategy link-most-common-toponym --baseline-strategy regdist-most-common-toponym')
TwitterDevStrategy2 = add_param('--strategy baseline --baseline-strategy link-most-common-toponym')
TwitterDevStrategy3 = add_param('--strategy baseline --baseline-strategy num-articles --baseline-strategy random')
TwitterDev1 = nest(TwitterDPR3, TwitterDevSet, TwitterDevStrategy1)
TwitterDev2 = nest(TwitterDPR3, TwitterDevSet, TwitterDevStrategy2)
TwitterDev3 = nest(TwitterDPR3, TwitterDevSet, TwitterDevStrategy3)
TwitterDPR4 = iterate('--degrees-per-region', [3, 4, 6, 7])
TwitterDev4 = nest(TwitterDPR4, TwitterDevSet, TwitterDevStrategy1)
TwitterDev5 = nest(TwitterDPR4, TwitterDevSet, TwitterDevStrategy2)
TwitterDev6 = nest(TwitterDPR4, TwitterDevSet, TwitterDevStrategy3)


WithStopwords = add_param('--include-stopwords-in-article-dists')
TwitterExper4 = nest(WithStopwords, TwitterDPR3, KLDivStrategy)
TwitterExper5 = nest(WithStopwords, TwitterDPR3, TwitterStrategy2)
TwitterExper6 = nest(WithStopwords, TwitterDPR3, BaselineStrategies)

TwitterWikiNumTest = iterate('--num-test-docs', [1894])
TwitterWikiDPR1 = iterate('--degrees-per-region', [0.1])
TwitterWikiStrategyAll = add_param('--strategy partial-kl-divergence --strategy naive-bayes-with-baseline --strategy smoothed-cosine-similarity --strategy per-word-region-distribution')
TwitterWikiDPR2 = iterate('--degrees-per-region', [0.5])
TwitterWikiDPR3 = iterate('--degrees-per-region', [5, 10, 1])
TwitterWikiStrategy3 = add_param('--strategy partial-kl-divergence')
TwitterWikiDPR4 = iterate('--degrees-per-region', [5, 10, 1])
TwitterWikiStrategy4 = add_param('--strategy naive-bayes-with-baseline --strategy smoothed-cosine-similarity --strategy per-word-region-distribution')
TwitterWikiExper1 = nest(Train100k, TwitterWikiNumTest, TwitterWikiDPR1, TwitterWikiStrategyAll)
TwitterWikiExper2 = nest(Train100k, TwitterWikiNumTest, TwitterWikiDPR2, TwitterWikiStrategyAll)
TwitterWikiExper3 = nest(Train100k, TwitterWikiNumTest, TwitterWikiDPR3, TwitterWikiStrategy3)
TwitterWikiExper4 = nest(Train100k, TwitterWikiNumTest, TwitterWikiDPR4, TwitterWikiStrategy4)

# Test 

main()
