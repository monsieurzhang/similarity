# -*- coding: utf-8 -*-

import tensorflow as tf
import numpy as np
import io
import os
import sys
import json
from shutil import copyfile
from dataset import Vocab, Embeddings, check_dataset


class Config():

    def __init__(self, argv):
        self.usage = """usage: {}
*  -mdir          FILE : directory to save/restore models

   -seq_size       INT : sentences larger than this number of src/tgt words are filtered out [50]
   -batch_size     INT : number of examples per batch [32]
   -seed           INT : seed for randomness [1234]
   -debug              : debug mode
   -h                  : this message

 [LEARNING OPTIONS]
*  -trn           FILE : training data
   -dev           FILE : validation data

   -src_tok       FILE : if provided, json tokenization options for onmt tokenization, points to vocabulary file
   -src_voc       FILE : vocabulary of src words (needed to initialize learning)
   -tgt_tok       FILE : if provided, json tokenization options for onmt tokenization, points to vocabulary file
   -tgt_voc       FILE : vocabulary of tgt words (needed to initialize learning)
   -src_emb       FILE : embeddings of src words (needed to initialize learning)
   -tgt_emb       FILE : embeddings of tgt words (needed to initialize learning)
   -src_emb_size   INT : size of src embeddings if -src_emb not used
   -tgt_emb_size   INT : size of tgt embeddings if -tgt_emb not used

   -src_lstm_size  INT : hidden units for src bi-lstm [256]
   -tgt_lstm_size  INT : hidden units for tgt bi-lstm [256]

   -lr           FLOAT : initial learning rate [1.0]
   -lr_decay     FLOAT : learning rate decay [0.9]
   -lr_method   STRING : GD method either: adam, adagrad, adadelta, sgd, rmsprop [adagrad]
   -aggr          TYPE : aggregation operation: sum, max, lse [lse]
   -r            FLOAT : r for lse [1.0]
   -dropout      FLOAT : dropout ratio [0.3]
   -mode        STRING : mode (alignment, sentence) [alignment]
   -max_sents      INT : Consider this number of sentences per batch (0 for all) [0]
   -n_epochs       INT : train for this number of epochs [1]
   -report_every   INT : report every this many batches [1000]

 [INFERENCE OPTIONS]
   -epoch          INT : epoch to use (mdir]/epoch[epoch], by default the latest one in mdir)
*  -tst           FILE : testing data
   -output        FILE : output file [- by default is STDOUT]
   -q                  : quiet mode, just output similarity score
   -show_matrix        : output formatted alignment matrix (mode must be alignment)
   -show_svg           : output alignment matrix using svg-like html format (mode must be alignment)
   -show_align         : output source/target alignment matrix (mode must be alignment)
   -show_last          : output source/target last vectors
   -show_aggr          : output source/target aggr vectors

+ Options marked with * must be set. The other ones have default values.
+ If -mdir exists in learning mode, learning continues after restoring the last model
+ Training data is shuffled at every epoch
+ -show_last, -show_aggr and -show_align can be used at the same time
""".format(argv.pop(0))

        self.src_voc = None
        self.src_tok = None
        self.tok_src = None
        self.tgt_voc = None
        self.tgt_tok = None
        self.tok_tgt = None
        self.src_emb = None
        self.tgt_emb = None
        self.src_voc_size = None
        self.tgt_voc_size = None
        self.src_emb_size = None
        self.tgt_emb_size = None
        self.mdir = None
        self.epoch = None
        self.trn = None
        self.dev = None
        self.tst = None
        self.output = '-'
        self.emb_src = None
        self.emb_tgt = None

        self.src_lstm_size = 256
        self.tgt_lstm_size = 256

        self.aggr = "lse"
        self.r = 1.0
        self.dropout = 0.3
        self.lr = 1.0
        self.lr_decay = 0.9
        self.lr_method = "adagrad"

        self.seq_size = 50
        self.batch_size = 32
        self.max_sents = 0
        self.n_epochs = 1
        # epochs already run
        self.last_epoch = 0
        self.seed = 1234
        self.report_every = 1000
        self.debug = False
        self.mode = "alignment"

        self.quiet = False
        self.show_matrix = False
        self.show_svg = False
        self.show_last = False
        self.show_aggr = False
        self.show_align = False

        self.parse(argv)

        tf.set_random_seed(self.seed)
        np.random.seed(self.seed)

        if not self.mdir:
            sys.stderr.write("error: Missing -mdir option\n{}".format(self.usage))
            sys.exit(1)

        if self.tst:
            self.inference()
        if self.trn:
            self.learn()
        return

    def inference(self):
        self.dropout = 0.0
        self.seq_size = 0
        if not self.epoch:
            for e in range(999, 0, -1):
                if os.path.exists(self.mdir+"/epoch{}.index".format(e)):
                    self.epoch = e
                    break
            if not self.epoch:
                sys.stderr.write("error: Cannot find epoch in mdir '{}'\n{}".format(self.mdir, self.usage))
                sys.exit(1)
        check_dataset(self.tst)
        if self.output == '-':
            self.output = sys.stdout
        else:
            self.output = open(self.output, "wb")
        if not os.path.exists('{}/epoch{}.index'.format(self.mdir, self.epoch)):
            sys.stderr.write('error: -epoch file {}/epoch{}.index cannot be find\n'.format(self.mdir, self.epoch))
            sys.exit(1)
        if not os.path.exists(self.mdir + '/topology'):
            sys.stderr.write('error: topology file: {} cannot be find\n'.format(self.mdir + '/topology'))
            sys.exit(1)
        src_voc = 'vocab_src'
        tgt_voc = 'vocab_tgt'
        if os.path.exists(self.mdir + '/tokenization_src.json'):
            with open(self.mdir + '/tokenization_src.json') as jsonfile:
                self.tok_src = json.load(jsonfile)
            src_voc = self.tok_src["vocabulary"]
        else:
            self.tok_src = None
        if not os.path.exists(self.mdir + '/' + src_voc):
            sys.stderr.write('error: vocab src file: {} cannot be find\n'.format(self.mdir + '/' + src_voc))
            sys.exit(1)
        if os.path.exists(self.mdir + '/tokenization_tgt.json'):
            with open(self.mdir + '/tokenization_tgt.json') as jsonfile:
                self.tok_tgt = json.load(jsonfile)
            tgt_voc = self.tok_tgt["vocabulary"]
        else:
            self.tok_tgt = None
        argv = []
        with open(self.mdir + "/topology", 'r') as f:
            for line in f:
                opt, val = line.split()
                argv.append('-'+opt)
                argv.append(val)
        # overrides options passed in command line
        self.parse(argv)

        # read vocabularies
        self.voc_src = Vocab(self.mdir + "/" + src_voc)
        self.voc_tgt = Vocab(self.mdir + "/" + tgt_voc)
        return

    def learn(self):
        check_dataset(self.trn)
        if self.dev is not None:
            check_dataset(self.dev)

        ###
        #  continuation
        ###
        if os.path.exists(self.mdir):
            src_voc = 'vocab_src'
            tgt_voc = 'vocab_tgt'
            if not os.path.exists(self.mdir + '/topology'):
                sys.stderr.write('error: topology file: {} cannot be find\n'.format(self.mdir + '/topology'))
                sys.exit(1)
            if os.path.exists(self.mdir + '/tokenization_src.json'):
                with open(self.mdir + '/tokenization_src.json') as jsonfile:
                    self.tok_src = json.load(jsonfile)
                src_voc = self.tok_src["vocabulary"]
            else:
                self.src_tok = None
            if not os.path.exists(self.mdir + '/' + src_voc):
                sys.stderr.write('error: vocab src file: {} cannot be find\n'.format(self.mdir + '/' + src_voc))
                sys.exit(1)
            if os.path.exists(self.mdir + '/tokenization_tgt.json'):
                with open(self.mdir + '/tokenization_tgt.json') as jsonfile:
                    self.tok_tgt = json.load(jsonfile)
                tgt_voc = self.tok_tgt["vocabulary"]
            else:
                self.tgt_tok = None
            if not os.path.exists(self.mdir + '/' + tgt_voc):
                sys.stderr.write('error: vocab tgt file: {} cannot be find\n'.format(self.mdir + '/' + tgt_voc))
                sys.exit(1)
            if not os.path.exists(self.mdir + '/checkpoint'):
                sys.stderr.write('error: checkpoint file: {} cannot be find\ndelete dir {} ???\n'.format(
                    self.mdir + '/checkpoint', self.mdir))
                sys.exit(1)

            argv = []
            with open(self.mdir + "/topology", 'r') as f:
                for line in f:
                    opt, val = line.split()
                    argv.append('-'+opt)
                    argv.append(val)
            # overrides options passed in command line
            self.parse(argv)
            # read vocabularies
            self.voc_src = Vocab(self.mdir + "/" + src_voc)
            self.voc_tgt = Vocab(self.mdir + "/" + tgt_voc)
            # update last epoch
            for e in range(999, 0, -1):
                if os.path.exists(self.mdir+"/epoch{}.index".format(e)):
                    self.last_epoch = e
                    break
            print("learning continuation: last epoch is {}".format(self.last_epoch))
        ###
        #   learning from scratch
        ###
        else:
            # read file or config/vocab_src if file is not set
            if self.src_tok:
                if not os.path.exists(self.src_tok):
                    sys.stderr.write('error: cannot find -src_tok file: {}\n'.format(self.src_tok))
                    sys.exit(1)
                with open(self.src_tok) as jsonfile:
                    self.tok_src = json.load(jsonfile)
                if not self.src_voc:
                    self.src_voc = self.tok_src["vocabulary"]
            else:
                self.tok_src = None

            self.voc_src = Vocab(self.src_voc)

            if self.tgt_tok:
                if not os.path.exists(self.tgt_tok):
                    sys.stderr.write('error: cannot find -tgt_tok file: {}\n'.format(self.tgt_tok))
                    sys.exit(1)
                with open(self.tgt_tok) as jsonfile:
                    self.tok_tgt = json.load(jsonfile)
                if not self.tgt_voc:
                    self.tgt_voc = self.tok_tgt["vocabulary"]
            else:
                self.tok_tgt = None

            self.voc_tgt = Vocab(self.tgt_voc)

            self.src_voc_size = self.voc_src.length
            self.tgt_voc_size = self.voc_tgt.length

            if not os.path.exists(self.mdir):
                os.makedirs(self.mdir)
            # copy vocabularies
            if self.src_tok:
                copyfile(self.src_voc, self.mdir + "/" + self.tok_src["vocabulary"])
                copyfile(self.src_tok, self.mdir + "/tokenization_src.json")
            else:
                copyfile(self.src_voc, self.mdir + "/vocab_src")

            if self.tgt_tok:
                copyfile(self.tgt_voc, self.mdir + "/" + self.tok_tgt["vocabulary"])
                copyfile(self.tgt_tok, self.mdir + "/tokenization_tgt.json")
            else:
                copyfile(self.tgt_voc, self.mdir + "/vocab_tgt")

            # read embeddings
            # read file or use emb_src.length if file is not set
            self.emb_src = Embeddings(self.src_emb, self.voc_src, self.src_emb_size)
            self.src_emb_size = self.emb_src.dim
            # read file or use emb_tgt.length if file is not set
            self.emb_tgt = Embeddings(self.tgt_emb, self.voc_tgt, self.tgt_emb_size)
            self.tgt_emb_size = self.emb_tgt.dim
            # write topology file
            with open(self.mdir + "/topology", 'w') as f:
                for opt, val in vars(self).items():
                    if opt.startswith("src") or opt.startswith("tgt") or \
                            opt == "aggr" or opt == "mode":
                        f.write("{} {}\n".format(opt, val))
            print("learning from scratch")
        return

    def parse(self, argv):
        while len(argv):
            tok = argv.pop(0)
            if (tok == "-mdir" and len(argv)):
                self.mdir = argv.pop(0)
            elif (tok == "-epoch" and len(argv)):
                self.epoch = int(argv.pop(0))
            elif (tok == "-src_tok" and len(argv)):
                self.src_tok = argv.pop(0)
            elif (tok == "-tgt_tok" and len(argv)):
                self.tgt_tok = argv.pop(0)
            elif (tok == "-src_voc" and len(argv)):
                self.src_voc = argv.pop(0)
            elif (tok == "-tgt_voc" and len(argv)):
                self.tgt_voc = argv.pop(0)
            elif (tok == "-src_emb" and len(argv)):
                self.src_emb = argv.pop(0)
            elif (tok == "-tgt_emb" and len(argv)):
                self.tgt_emb = argv.pop(0)
            elif (tok == "-src_voc_size" and len(argv)):
                self.src_voc_size = int(argv.pop(0))
            elif (tok == "-tgt_voc_size" and len(argv)):
                self.tgt_voc_size = int(argv.pop(0))
            elif (tok == "-src_emb_size" and len(argv)):
                self.src_emb_size = int(argv.pop(0))
            elif (tok == "-tgt_emb_size" and len(argv)):
                self.tgt_emb_size = int(argv.pop(0))
            elif (tok == "-trn" and len(argv)):
                self.trn = argv.pop(0)
            elif (tok == "-dev" and len(argv)):
                self.dev = argv.pop(0)
            elif (tok == "-tst" and len(argv)):
                self.tst = argv.pop(0)
            elif (tok == "-output" and len(argv)):
                self.output = argv.pop(0)
            elif (tok == "-max_sents" and len(argv)):
                self.max_sents = int(argv.pop(0))
            elif (tok == "-debug"):
                self.debug = True
            elif (tok == "-seed" and len(argv)):
                self.seed = int(argv.pop(0))
            elif (tok == "-report_every" and len(argv)):
                self.report_every = int(argv.pop(0))
            elif (tok == "-n_epochs" and len(argv)):
                self.n_epochs = int(argv.pop(0))

            elif (tok == "-src_lstm_size" and len(argv)):
                self.src_lstm_size = int(argv.pop(0))
            elif (tok == "-tgt_lstm_size" and len(argv)):
                self.tgt_lstm_size = int(argv.pop(0))

            elif (tok == "-seq_size" and len(argv)):
                self.seq_size = int(argv.pop(0))
            elif (tok == "-batch_size" and len(argv)):
                self.batch_size = int(argv.pop(0))
            elif (tok == "-aggr" and len(argv)):
                self.aggr = argv.pop(0)
            elif (tok == "-r" and len(argv)):
                self.r = float(argv.pop(0))
            elif (tok == "-dropout" and len(argv)):
                self.dropout = float(argv.pop(0))
            elif (tok == "-lr" and len(argv)):
                self.lr = float(argv.pop(0))
            elif (tok == "-lr_decay" and len(argv)):
                self.lr_decay = float(argv.pop(0))
            elif (tok == "-lr_method" and len(argv)):
                self.lr_method = argv.pop(0)
            elif (tok == "-mode" and len(argv)):
                self.mode = argv.pop(0)

            elif tok == "-q":
                self.quiet = True
            elif tok == "-show_matrix":
                self.show_matrix = True
            elif tok == "-show_svg":
                self.show_svg = True
            elif tok == "-show_aggr":
                self.show_aggr = True
            elif tok == "-show_last":
                self.show_last = True
            elif tok == "-show_align":
                self.show_align = True

            elif tok == "-h":
                sys.stderr.write("{}".format(self.usage))
                sys.exit(0)

            else:
                sys.stderr.write('error: unparsed {} option\n'.format(tok))
                sys.stderr.write("{}".format(self.usage))
                sys.exit(1)

    def write_config(self):
        if not os.path.exists(self.mdir):
            os.makedirs(self.mdir)
        file = "{}/epoch{}.config".format(self.mdir, self.last_epoch)
        with open(file, "w") as f:
            for name, val in vars(self).items():
                if name == "usage" or name.startswith("emb_") or name.startswith("voc_"):
                    continue
                f.write("{} {}\n".format(name, val))
