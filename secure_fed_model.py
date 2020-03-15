#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Mar 13 09:51:14 2020

@author: shah38
"""


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Feb 25 11:46:02 2020

@author: shah38
"""

import nest_asyncio
nest_asyncio.apply()

import collections

import numpy as np
import tensorflow as tf
import ssl
import time
import collections
import os
from keras.utils.np_utils import to_categorical
import warnings
import sys
from phe import paillier
from sklearn.metrics import roc_auc_score

keras = tf.keras
ssl._create_default_https_context = ssl._create_unverified_context
np.random.seed(0)
tf.compat.v1.enable_v2_behavior()
warnings.filterwarnings("ignore")
# make up our client scenario
NUM_CLIENTS=2
NUM_TRAIN_CLIENTS=(int)(0.8*NUM_CLIENTS)
NUM_TEST_CLIENTS = NUM_CLIENTS-NUM_TRAIN_CLIENTS
DATASET_SIZE = 30000
TRAIN_SIZE = int(0.8 * DATASET_SIZE)
TEST_SIZE = int(0.2 * DATASET_SIZE)

CLIENT_SIZE = (int)(TRAIN_SIZE/NUM_CLIENTS)
CLIENT_TRAIN_SIZE = int(0.8 * CLIENT_SIZE)
CLIENT_TEST_SIZE = int(0.2 * CLIENT_SIZE)

BATCH_SIZE = 32
IMG_SHAPE=(10, 10, 3)
base_learning_rate = 0.001
 

# Timer helper class for benchmarking reading methods
class Timer(object):
    """Timer class
       Wrap a will with a timing function
    """
    
    def __init__(self, name):
        self.name = name
        
    def __enter__(self):
        self.t = time.time()
        
    def __exit__(self, *args, **kwargs):
        print("{} took {} seconds".format(
        self.name, time.time() - self.t))
    
weights_shape = [(3, 3, 3, 32),
(32,),
(128, 8),
(8,),
(8, 1),
(1,)]
def auroc(y_true, y_pred):
    return tf.compat.v1.py_func(roc_auc_score, (y_true, y_pred), tf.double)

def create_model():
    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Conv2D(32, kernel_size=(3, 3),
                      activation='relu',
                      input_shape=(10,10,3),strides=2))
    model.add(tf.keras.layers.MaxPooling2D(pool_size=(2, 2)))
    model.add(tf.keras.layers.Dropout(0.25))
    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(8, activation='relu'))
    model.add(tf.keras.layers.Dropout(0.5))
    model.add(tf.keras.layers.Dense(1)) 
    model.compile(optimizer=tf.keras.optimizers.RMSprop(lr=base_learning_rate),
      loss=tf.keras.losses.BinaryCrossentropy(from_logits=True),
      metrics=[tf.keras.metrics.BinaryAccuracy(),auroc])
    return model


class Client(object):
    def __init__(self, data, num, secure):
        self.model = create_model()
        self.public_key, self.private_key = paillier.generate_paillier_keypair()
        self.train = prepare_for_training(data.take(CLIENT_TRAIN_SIZE))
        self.validation = prepare_for_training(data.skip(CLIENT_TRAIN_SIZE).take(CLIENT_TEST_SIZE))
        self.secure = secure
        self.id = num
        
    def enc(self, x):
        return self.public_key.encrypt((float)(x))

    def dec(self, x):
        return np.float32((self.private_key.decrypt(x)))
        
    def enc_model(self, x):
        enc_vector = np.vectorize(self.enc)
        arry_weights = np.array(x.get_weights())
        for i in range(arry_weights.shape[0]):
            layer = arry_weights[i]
            print(layer.shape)
            arry_weights[i] = np.apply_along_axis(enc_vector,0,arry_weights[i])
            # print("orig", layer.shape)
            # layer = layer.flatten()
            # print("flatten ", layer.shape)
            # layer = enc_vector(layer)
            # layer = layer.reshape(weights_shape[i])
            # print("reshape ", layer.shape)
            # arry_weights[i] = layer
        x.set_weights(arry_weights)    
        return x
    def dec_model(self, x):
        dec_vector = np.vectorize(self.dec)
        arry_weights = np.array(x.get_weights())
        for i in range(arry_weights.shape[0]):
            arry_weights[i] = np.apply_along_axis(dec_vector,0,arry_weights[i])
        x.set_weights(arry_weights)    
        return x
    
    def client_fit(self, epochs=10):
        with Timer("Training for client " + str(self.id)):
            history = self.model.fit(self.train,
                                epochs=epochs,
                                validation_data=self.validation)
        if self.secure:
            with Timer("Encryption for client " + str(self.id)):
                self.enc_model(self.model)    
        return self.model, history    
    
    def client_update(self, model):
        if NUM_CLIENTS==1:
            return
        
        if self.secure:
            with Timer("Decryption for client " + str(self.id)):
                self.model = self.dec_model(model)
        else:
            self.model = model
         
    def evaluate(self, test_batches):
        loss,accuracy,auc = self.model.evaluate(test_batches, steps = 20)
        return loss, accuracy, auc       
            
class Server(object):
    def __init__(self):
        self.model = create_model()
        
    def aggregate(self, client_models):
        if NUM_CLIENTS==1:
            self.model = client_models[0]
            return self.model
        weights = [model.get_weights() for model in client_models]
        ave_weights = list()
        for weights_list_tuple in zip(*weights): 
            ave_weights.append(
                np.array([np.array(w).mean(axis=0) for w in zip(*weights_list_tuple)])
                )
        self.model.set_weights(ave_weights)
        return self.model


        

def get_label(file_path):
    parts = tf.strings.split(file_path, os.path.sep)
    return (int)(parts[-2] == '1')
def decode_img(img):
    img = tf.image.decode_png(img, channels=3)
    img = tf.image.convert_image_dtype(img, tf.float32)
    return tf.image.resize(img, [10, 10])
def process_path(file_path):
    label = get_label(file_path)
    img = tf.io.read_file(file_path)
    img = decode_img(img)
    return img, label

def prepare_for_training(ds, cache=True, shuffle_buffer_size=1000):
    # This is a small dataset, only load it once, and keep it in memory.
    # use `.cache(filename)` to cache preprocessing work for datasets that don't
    # fit in memory.
    if cache:
        if isinstance(cache, str):
            ds = ds.cache(cache)
        else:
            ds = ds.cache()

    ds = ds.shuffle(buffer_size=shuffle_buffer_size)

    ds = ds.batch(BATCH_SIZE)

    # `prefetch` lets the dataset fetch batches in the background while the model
    # is training.
    ds = ds.prefetch(buffer_size=tf.data.experimental.AUTOTUNE)

    return ds

def create_clients(all_data, client_ids,secure):
  clients=[]
  for i in client_ids:
      clients.append(Client(all_data.shard(NUM_CLIENTS,i),i,secure))
  return clients    
    
def main():
    path_data = sys.argv[1]
    NUM_ROUNDS=(int)(sys.argv[2])
    secure = sys.argv[3]
    epochs=5
    list_ds = tf.data.Dataset.list_files(path_data + '/data/balanced_IDC_30k/*/*', shuffle=True)  
    labeled_ds = list_ds.map(process_path, num_parallel_calls=tf.data.experimental.AUTOTUNE)
    client_data = labeled_ds.take(TRAIN_SIZE)
    test_data = prepare_for_training(labeled_ds.skip(TRAIN_SIZE).take(TEST_SIZE))
    clients = create_clients(client_data, np.arange(NUM_CLIENTS),secure=="secure")
    #clients[0].enc_model(clients[0].model)
    server = Server()
    with Timer("Secure fed model"):
        for i in np.arange(NUM_ROUNDS):
            model_updates = []
            for c in clients:
                new_model, history = c.client_fit(epochs)
                model_updates.append(new_model)
                
            ave_model = server.aggregate(model_updates)
            
            for c in clients:
                c.client_update(ave_model)
            
            loss,acc,auc = clients[0].evaluate(test_data)
            print(loss,acc,auc)
    
          
if __name__ == "__main__":
    main()
