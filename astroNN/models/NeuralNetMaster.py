###############################################################################
#   NeuralNetMaster.py: top-level class for a neural network
###############################################################################
import os
import sys
import time
from abc import ABC, abstractmethod

import keras
import keras.backend as K
import tensorflow as tf
from keras.utils import plot_model

import astroNN
from astroNN.shared.nn_tools import folder_runnum, cpu_fallback, gpu_memory_manage


K.set_learning_phase(1)


class NeuralNetMaster(ABC):
    """Top-level class for a neural network"""

    def __init__(self):
        """
        NAME:
            __init__
        PURPOSE:
            To define astroNN neural network
        HISTORY:
            2017-Dec-23 - Written - Henry Leung (University of Toronto) \
            2018-Jan-05 - Update - Henry Leung (University of Toronto)
        """
        self.name = None
        self._model_type = None
        self._model_identifier = None
        self._implementation_version = None
        self.__python_info = sys.version
        self.__astronn_ver = astroNN.__version__
        self.__keras_ver = keras.__version__
        self.__tf_ver = tf.__version__
        self.fallback_cpu = False
        self.limit_gpu_mem = True
        self.currentdir = os.getcwd()
        self.folder_name = None
        self.fullfilepath = None

        # Hyperparameter
        self.task = None
        self.batch_size = None
        self.lr = None
        self.max_epochs = None
        self.val_size = None
        self.val_num = None

        # optimizer parameter
        self.beta_1 = 0.9  # exponential decay rate for the 1st moment estimates for optimization algorithm
        self.beta_2 = 0.999  # exponential decay rate for the 2nd moment estimates for optimization algorithm
        self.optimizer_epsilon = K.epsilon()  # a small constant for numerical stability for optimization algorithm
        self.optimizer = None

        # Keras API
        self.keras_model = None
        self.metrics = None

        self.input_normalizer = None
        self.labels_normalizer = None
        self.training_generator = None

        self.input_norm_mode = None
        self.labels_norm_mode = None

        self.input_shape = None
        self.labels_shape = None

        self.num_train = None
        self.targetname = None

    @abstractmethod
    def train(self, *args):
        raise NotImplementedError

    @abstractmethod
    def test(self, *args):
        raise NotImplementedError

    @abstractmethod
    def model(self):
        raise NotImplementedError

    def cpu_gpu_check(self):
        if self.fallback_cpu is True:
            cpu_fallback()

        if self.limit_gpu_mem is True:
            gpu_memory_manage()
        elif isinstance(self.limit_gpu_mem, float) is True:
            gpu_memory_manage(ratio=self.limit_gpu_mem)

    def pre_training_checklist_master(self, input_data, labels):
        if self.val_size is None:
            self.val_size = 0
        self.val_num = int(input_data.shape[0] * self.val_size)
        self.num_train = input_data.shape[0] - self.val_num

        if input_data.ndim == 2:
            self.input_shape = (input_data.shape[1], 1,)
        elif input_data.ndim == 3:
            self.input_shape = (input_data.shape[1], input_data.shape[2], 1,)
        elif input_data.ndim == 4:
            self.input_shape = (input_data.shape[1], input_data.shape[2], input_data.shape[3],)

        if labels.ndim == 2:
            self.labels_shape = labels.shape[1]
        elif labels.ndim == 3:
            self.labels_shape = (labels.shape[1], labels.shape[2])
        elif labels.ndim == 4:
            self.labels_shape = (labels.shape[1], labels.shape[2], labels.shape[3])

        self.cpu_gpu_check()

        self.folder_name = folder_runnum()
        self.fullfilepath = os.path.join(self.currentdir, self.folder_name + '/')

        with open(self.fullfilepath + 'hyperparameter.txt', 'w') as h:
            h.write("model: {} \n".format(self.name))
            h.write("model type: {} \n".format(self._model_type))
            h.write("astroNN identifier: {} \n".format(self._model_identifier))
            h.write("model version: {} \n".format(self.__python_info))
            h.write("astroNN version: {} \n".format(self.__astronn_ver))
            h.write("keras version: {} \n".format(self.__keras_ver))
            h.write("tensorflow version: {} \n".format(self.__tf_ver))
            h.write("folder name: {} \n".format(self.folder_name))
            h.write("fallback cpu? : {} \n".format(self.fallback_cpu))
            h.write("astroNN GPU management: {} \n".format(self.limit_gpu_mem))
            h.write("batch_size: {} \n".format(self.batch_size))
            h.write("optimizer: {} \n".format(self.optimizer))
            h.write("max_epochs: {} \n".format(self.max_epochs))
            h.write("learning rate: {} \n".format(self.lr))
            h.write("Validation Size: {} \n".format(self.val_size))
            h.write("training input shape: {} \n".format(self.input_shape))
            h.write("label shape: {} \n".format(self.labels_shape))
            h.close()

        print('Number of Training Data: {}, Number of Validation Data: {}'.format(self.num_train, self.val_num))

    def post_training_checklist_master(self):
        pass

    def plot_model(self):
        try:
            plot_model(self.keras_model, show_shapes=True, to_file=self.fullfilepath + 'model.png')
        except all:
            print('Skipped plot_model! graphviz and pydot_ng are required to plot the model architecture')
            pass

    def jacobian_1(self, x=None, plotting=True):
        """
        NAME: cal_jacobian
        PURPOSE: calculate jacobian
        INPUT:
        OUTPUT:
        HISTORY:
            2017-Nov-20 Henry Leung
        """
        import numpy as np

        if x is None:
            raise ValueError('Please provide data to calculate the jacobian')

        dr = 14

        x = np.atleast_3d(x)
        # enforce float16 because the precision doesnt really matter
        input_tens = self.keras_model.get_layer("input").input
        jacobian = np.ones((self.labels_shape, x.shape[1], x.shape[0]), dtype=np.float16)
        start_time = time.time()
        K.set_learning_phase(0)

        with K.get_session() as sess:
            for counter, j in enumerate(range(self.labels_shape)):
                print('Completed {} of {} output, {:.03f} seconds elapsed'.format(counter + 1, self.labels_shape,
                                                                                  time.time() - start_time))
                grad = self.keras_model.get_layer("output").output[0, j]
                grad_wrt_input_tensor = K.tf.gradients(grad, input_tens)
                for i in range(x.shape[0]):
                    x_in = x[i:i + 1]
                    jacobian[j, :, i:i + 1] = (np.asarray(sess.run(grad_wrt_input_tensor,
                                                                   feed_dict={input_tens: x_in})[0]))

        K.clear_session()

        return jacobian
