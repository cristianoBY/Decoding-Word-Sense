
# coding: utf-8

# In[1]:


import csv
import math
import string
import itertools
from io import open
import nltk
from nltk.corpus import wordnet as wn
import numpy as np
import pickle
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from collections import Iterable, defaultdict
import random


# In[2]:


# set determinstic results
SEED = 1234
random.seed(SEED)
torch.manual_seed(SEED)
torch.backends.cudnn.deterministic = True


# In[3]:


from allennlp.commands.elmo import ElmoEmbedder
elmo = ElmoEmbedder()

from encoder import *
from decoder import *
from emb2seq_model import *

# get the decoder vocab
with open('./data/vocab.pkl', 'rb') as f:
    vocab = pickle.load(f)
    print("Size of vocab: {}".format(vocab.idx))


# In[ ]:


decoder = Decoder(vocab_size = vocab.idx)
encoder = Encoder(elmo_class = elmo)
emb2seq_model = Emb2Seq_Model(encoder, decoder, vocab = vocab)

# randomly initialize the weights
def init_weights(m):
    for name, param in m.named_parameters():
        nn.init.uniform_(param.data, -0.08, 0.08)       
emb2seq_model.apply(init_weights)


# In[ ]:


# training hyperparameters
optimizer = optim.Adam(emb2seq_model.parameters())
PAD_IDX = vocab('<pad>')
print('PAD_IDX: {}'.format(PAD_IDX))
criterion = nn.CrossEntropyLoss(ignore_index = PAD_IDX)

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('Device: {}'.format(device))
print(torch.cuda.device_count())
emb2seq_model.to(device)


# In[ ]:


# utility function
# turn the given definition into its index list form
def def2idx(definition, max_length, vocab):
    
    # definition is given by the WN NLTK API in a string
    def_tokens = nltk.tokenize.word_tokenize(definition.lower())
    
    # limit the length if too long, trim
    if len(def_tokens) > (max_length - 2):
        def_tokens = def_tokens[0:(max_length - 2)]
        
        # add the start and end symbol
        def_tokens = ['<start>'] + def_tokens + ['<end>']
    
    # if the length is too short, pad
    elif len(def_tokens) < (max_length - 2):
        
        # add the start and end symbol
        def_tokens = ['<start>'] + def_tokens + ['<end>']
        
        pad = ['<pad>'] * (max_length - len(def_tokens))
        def_tokens = def_tokens + pad
        
    else:
        def_tokens = ['<start>'] + def_tokens + ['<end>']
            
    # get the index for each element in the token list
    def_idx_list = [vocab(token) for token in def_tokens]
    
    return def_idx_list
  


# In[ ]:


# parse the SemCor training data
import xml.etree.ElementTree as ET
tree = ET.parse('../../Downloads/WSD_Evaluation_Framework/Training_Corpora/SemCor/semcor.data.xml')
corpus = tree.getroot()

# parse the target sense tag 
target_file = open("../../Downloads/WSD_Evaluation_Framework/Training_Corpora/SemCor/semcor.gold.key.txt", "r")


# In[ ]:


small_train_size = 1
small_dev_size = 1

# the training function
def train(model, optimizer, corpus, criterion, clip):
    
    model.train()
    epoch_loss = 0
    sn = 0
    
    for sub_corpus in corpus:
    
        for sent in sub_corpus:

            optimizer.zero_grad()

            # get the plain text sentence
            sentence = [word.text for word in sent]
            
            # get the tagged ambiguous words
            tagged_sent = [instance for instance in sent if instance.tag == 'instance']
            # print(sentence)
            # print(tagged_sent)
            
            # only use sentence with at least one tagged word
            if len(tagged_sent) > 0:
                
                print(sn)
                sn += 1
                
                # get all-word definitions, batch_size is the sentence length
                # [batch_size, self.max_length]
                definitions = []
                for instance in tagged_sent:
                    
                    # get the sense from the WN
                    # senses are in-order already
                    key = target_file.readline().replace('\n', '').split(' ')[-1]
                    definition = wn.lemma_from_key(key).synset().definition()                 
                    def_idx_list = def2idx(definition, model.max_length, vocab)
                    definitions.append(def_idx_list)

                # get the encoder-decoder result
                # (self.max_length, batch_size, vocab_size)
                output, result = model(sentence, tagged_sent, definitions, teacher_forcing_ratio = 0.4)

                # adjust dimension for loss calculation
                '''
                output = output.permute(1, 2, 0)
                # print(output.shape)
                target = torch.tensor(definitions, dtype = torch.long).to(device)

                loss = criterion(output, target).to(device)
                loss.backward()

                # add clip for gradient boost
                torch.nn.utils.clip_grad_norm_(model.parameters(), clip)

                optimizer.step()
                epoch_loss += loss.item()
                '''
        
    return epoch_loss / small_test_size, result


# In[ ]:


# evaluate the model
def evaluate(model, criterion):
    
    model.eval()
    epoch_loss = 0
    
    with torch.no_grad():
    
        for idx in range(small_dev_size):

            # get the semcor tagged sentence
            sentence = semcor.sents()[idx + small_train_size]
            tagged_sent = semcor.tagged_sents(tag = 'sem')[idx + small_train_size]
            print(idx)

            # get all-word definitions
            # [batch_size, self.max_length]
            definitions = []
            for idx, chunk in enumerate(tagged_sent):
                if isinstance(chunk, Tree):

                    # only take in ambiguous words
                    if isinstance(chunk.label(), nltk.corpus.reader.wordnet.Lemma):
                        # print(chunk.label())
                        synset = chunk.label().synset().name()
                        definition = wn.synset(synset).definition()
                        
                        print(definition)
                        def_idx_list = def2idx(definition, model.max_length, vocab)
                        definitions.append(def_idx_list)

            # get the encoder-decoder result
            # (max_length, batch_size, vocab_size)
            # turn off teacher forcing
            output, result = model(sentence, tagged_sent, definitions, teacher_forcing_ratio = 0)

            # adjust dimension for loss calculation
            output = output.permute(1, 2, 0)
            # print(output.shape)
            target = torch.tensor(definitions, dtype = torch.long).to(device)

            loss = criterion(output, target).to(device)         
            epoch_loss += loss.item()
        
    return epoch_loss / small_dev_size, result


# In[ ]:


# time used by each epoch
def epoch_time(start_time, end_time):
    elapsed_time = end_time - start_time
    elapsed_mins = int(elapsed_time / 60)
    elapsed_secs = int(elapsed_time - (elapsed_mins * 60))
    return elapsed_mins, elapsed_secs


# In[ ]:


# train and evaluate
import time

N_EPOCHS = 1
CLIP = 1
best_valid_loss = float('inf')

for epoch in range(N_EPOCHS):
    
    start_time = time.time()
    
    train_loss, _ = train(emb2seq_model, optimizer, corpus, criterion, CLIP)
    # valid_loss, result = evaluate(emb2seq_model, criterion)
    # print(result)
    
    end_time = time.time()
    
    epoch_mins, epoch_secs = epoch_time(start_time, end_time)
    
    # visualize the results
    '''
    for n in range(len(result[0])):
        sense = []
        for m in range(len(result)):
            w = vocab.idx2word.get(int(result[m][n]))
            sense.append(w)
        print(sense)
    '''
    # save the best model based on the dev set
    '''
    if valid_loss <= best_valid_loss:
        best_valid_loss = valid_loss
        torch.save(seq2seq_model.state_dict(), 'best_model.pth')
    '''
    
    print(f'Epoch: {epoch+1:02} | Time: {epoch_mins}m {epoch_secs}s')
    print(f'\tTrain Loss: {train_loss:.3f} | Train PPL: {math.exp(train_loss):7.3f}')
    # print(f'\t Val. Loss: {valid_loss:.3f} |  Val. PPL: {math.exp(valid_loss):7.3f}')


# In[ ]:


# plot the learning curve
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import rc

with open('train_loss.tsv', mode = 'w') as loss_file:
        
    csv_writer = csv.writer(loss_file)
    csv_writer.writerow(train_losses)

    
with open('dev_loss.tsv', mode = 'w') as loss_file:
        
    csv_writer = csv.writer(loss_file)
    csv_writer.writerow(dev_losses)


# In[ ]:


plt.figure(1)
# rc('text', usetex = True)
rc('font', family='serif')
plt.grid(True, ls = '-.',alpha = 0.4)
plt.plot(train_losses, ms = 4, marker = 's', label = "Train Loss")
plt.legend(loc = "best")
title = "Cosine Similarity Loss (number of examples: " + str(len(train_X)) + ")"
plt.title(title)
plt.ylabel('Loss')
plt.xlabel('Number of Iteration')
plt.tight_layout()
plt.savefig('train_loss.png')


# In[ ]:


plt.figure(2)
# rc('text', usetex = True)
rc('font', family='serif')
plt.grid(True, ls = '-.',alpha = 0.4)
plt.plot(dev_losses, ms = 4, marker = 'o', label = "Dev Loss")
plt.legend(loc = "best")
title = "Cosine Similarity Loss (number of examples: " + str(len(dev_X)) + ")"
plt.title(title)
plt.ylabel('Loss')
plt.xlabel('Number of Iteration')
plt.tight_layout()
plt.savefig('dev_loss.png')

