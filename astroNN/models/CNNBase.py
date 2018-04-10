import json
import os
from abc import ABC

import numpy as np
from sklearn.model_selection import train_test_split

from astroNN.config import MULTIPROCESS_FLAG
from astroNN.config import keras_import_manager
from astroNN.models.NeuralNetMaster import NeuralNetMaster
from astroNN.nn.callbacks import VirutalCSVLogger
from astroNN.nn.losses import categorical_cross_entropy, binary_cross_entropy
from astroNN.nn.losses import mean_squared_error, mean_absolute_error
from astroNN.nn.metrics import categorical_accuracy, binary_accuracy
from astroNN.nn.utilities import Normalizer
from astroNN.nn.utilities.generator import threadsafe_generator, GeneratorMaster

keras = keras_import_manager()
regularizers = keras.regularizers
ReduceLROnPlateau, EarlyStopping = keras.callbacks.ReduceLROnPlateau, keras.callbacks.EarlyStopping
Adam = keras.optimizers.Adam


class CNNDataGenerator(GeneratorMaster):
    """
    NAME:
        CNNDataGenerator
    PURPOSE:
        To generate data for Keras
    INPUT:
    OUTPUT:
    HISTORY:
        2017-Dec-02 - Written - Henry Leung (University of Toronto)
    """

    def __init__(self, batch_size, shuffle=True):
        super().__init__(batch_size, shuffle)

    def _data_generation(self, inputs, labels, idx_list_temp):
        x = self.input_d_checking(inputs, idx_list_temp)
        y = labels[idx_list_temp]

        return x, y

    @threadsafe_generator
    def generate(self, inputs, labels):
        # Infinite loop
        idx_list = range(inputs.shape[0])
        while 1:
            # Generate order of exploration of dataset
            indexes = self._get_exploration_order(idx_list)

            # Generate batches
            imax = int(len(indexes) / self.batch_size)
            for i in range(imax):
                # Find list of IDs
                idx_list_temp = indexes[i * self.batch_size:(i + 1) * self.batch_size]

                # Generate data
                x, y = self._data_generation(inputs, labels, idx_list_temp)

                yield x, y


class CNNPredDataGenerator(GeneratorMaster):
    """
    NAME:
        CNNPredDataGenerator
    PURPOSE:
        To generate data for Keras model prediction
    INPUT:
    OUTPUT:
    HISTORY:
        2017-Dec-02 - Written - Henry Leung (University of Toronto)
    """

    def __init__(self, batch_size, shuffle=False):
        super().__init__(batch_size, shuffle)

    def _data_generation(self, inputs, idx_list_temp):
        # Generate data
        x = self.input_d_checking(inputs, idx_list_temp)

        return x

    @threadsafe_generator
    def generate(self, inputs):
        # Infinite loop
        idx_list = range(inputs.shape[0])
        while 1:
            # Generate order of exploration of dataset
            indexes = self._get_exploration_order(idx_list)

            # Generate batches
            imax = int(len(indexes) / self.batch_size)
            for i in range(imax):
                # Find list of IDs
                idx_list_temp = indexes[i * self.batch_size:(i + 1) * self.batch_size]

                # Generate data
                x = self._data_generation(inputs, idx_list_temp)

                yield x


class CNNBase(NeuralNetMaster, ABC):
    """Top-level class for a convolutional neural network"""

    def __init__(self):
        """
        NAME:
            __init__
        PURPOSE:
            To define astroNN convolutional neural network
        HISTORY:
            2018-Jan-06 - Written - Henry Leung (University of Toronto)
        """
        super().__init__()
        self.name = 'Convolutional Neural Network'
        self._model_type = 'CNN'
        self._model_identifier = None
        self.initializer = None
        self.activation = None
        self._last_layer_activation = None
        self.num_filters = None
        self.filter_len = None
        self.pool_length = None
        self.num_hidden = None
        self.reduce_lr_epsilon = None
        self.reduce_lr_min = None
        self.reduce_lr_patience = None
        self.l2 = None
        self.dropout_rate = 0.0
        self.val_size = 0.1
        self.early_stopping_min_delta = 0.0001
        self.early_stopping_patience = 4

        self.input_norm_mode = 1
        self.labels_norm_mode = 2

    def test(self, input_data):
        self.pre_testing_checklist_master()

        if self.input_normalizer is not None:
            input_array = self.input_normalizer.normalize(input_data)
        else:
            # Prevent shallow copy issue
            input_array = np.array(input_data)
            input_array -= self.input_mean
            input_array /= self.input_std

        total_test_num = input_data.shape[0]  # Number of testing data

        # for number of training data smaller than batch_size
        if input_data.shape[0] < self.batch_size:
            self.batch_size = input_data.shape[0]

        # Due to the nature of how generator works, no overlapped prediction
        data_gen_shape = (total_test_num // self.batch_size) * self.batch_size
        remainder_shape = total_test_num - data_gen_shape  # Remainder from generator

        predictions = np.zeros((total_test_num, self.labels_shape))

        # Data Generator for prediction
        prediction_generator = CNNPredDataGenerator(self.batch_size).generate(input_array[:data_gen_shape])
        predictions[:data_gen_shape] = np.asarray(self.keras_model.predict_generator(
            prediction_generator, steps=input_array.shape[0] // self.batch_size))

        if remainder_shape != 0:
            remainder_data = input_array[data_gen_shape:]
            # assume its caused by mono images, so need to expand dim by 1
            if len(input_array[0].shape) != len(self.input_shape):
                remainder_data = np.expand_dims(remainder_data, axis=-1)
            result = self.keras_model.predict(remainder_data)
            predictions[data_gen_shape:] = result.reshape((remainder_shape, self.labels_shape))

        predictions *= self.labels_std
        predictions += self.labels_mean

        return predictions

    def compile(self, optimizer=None, loss=None, metrics=None, loss_weights=None, sample_weight_mode=None):
        if optimizer is not None:
            self.optimizer = optimizer
        elif self.optimizer is None or self.optimizer == 'adam':
            self.optimizer = Adam(lr=self.lr, beta_1=self.beta_1, beta_2=self.beta_2, epsilon=self.optimizer_epsilon,
                                  decay=0.0)

        if self.task == 'regression':
            self._last_layer_activation = 'linear'
            loss_func = mean_squared_error
            if self.metrics is None:
                self.metrics = [mean_absolute_error]
        elif self.task == 'classification':
            self._last_layer_activation = 'softmax'
            loss_func = categorical_cross_entropy
            if self.metrics is None:
                self.metrics = [categorical_accuracy]
        elif self.task == 'binary_classification':
            self._last_layer_activation = 'sigmoid'
            loss_func = binary_cross_entropy
            if self.metrics is None:
                self.metrics = [binary_accuracy(from_logits=False)]
        else:
            raise RuntimeError('Only "regression", "classification" and "binary_classification" are supported')

        self.keras_model = self.model()

        self.keras_model.compile(loss=loss_func, optimizer=self.optimizer, metrics=self.metrics, loss_weights=None)

        return None

    def pre_training_checklist_child(self, input_data, labels):
        self.pre_training_checklist_master(input_data, labels)

        # check if exists (exists mean fine-tuning, so we do not need calculate mean/std again)
        if self.input_normalizer is None:
            self.input_normalizer = Normalizer(mode=self.input_norm_mode)
            self.labels_normalizer = Normalizer(mode=self.labels_norm_mode)

            norm_data = self.input_normalizer.normalize(input_data)
            self.input_mean, self.input_std = self.input_normalizer.mean_labels, self.input_normalizer.std_labels
            norm_labels = self.labels_normalizer.normalize(labels)
            self.labels_mean, self.labels_std = self.labels_normalizer.mean_labels, self.labels_normalizer.std_labels
        else:
            norm_data = self.input_normalizer.denormalize(input_data)
            norm_labels = self.labels_normalizer.denormalize(labels)

        if self.keras_model is None:  # only compiler if there is no keras_model, e.g. fine-tuning does not required
            self.compile()

        train_idx, test_idx = train_test_split(np.arange(self.num_train), test_size=self.val_size)

        self.training_generator = CNNDataGenerator(self.batch_size).generate(norm_data[train_idx],
                                                                             norm_labels[train_idx])
        self.validation_generator = CNNDataGenerator(self.batch_size).generate(norm_data[test_idx],
                                                                               norm_labels[test_idx])

        return input_data, labels

    def post_training_checklist_child(self):
        astronn_model = 'model_weights.h5'
        self.keras_model.save(self.fullfilepath + astronn_model)
        print(astronn_model + f' saved to {(self.fullfilepath + astronn_model)}')

        self.hyper_txt.write(f"Dropout Rate: {self.dropout_rate} \n")
        self.hyper_txt.flush()
        self.hyper_txt.close()

        data = {'id': self.__class__.__name__ if self._model_identifier is None else self._model_identifier,
                'pool_length': self.pool_length, 'filterlen': self.filter_len,
                'filternum': self.num_filters, 'hidden': self.num_hidden, 'input': self.input_shape,
                'labels': self.labels_shape, 'task': self.task, 'input_mean': self.input_mean.tolist(),
                'labels_mean': self.labels_mean.tolist(), 'input_std': self.input_std.tolist(),
                'labels_std': self.labels_std.tolist(),
                'valsize': self.val_size, 'targetname': self.targetname, 'dropout_rate': self.dropout_rate,
                'l2': self.l2, 'input_norm_mode': self.input_norm_mode, 'labels_norm_mode': self.labels_norm_mode,
                'batch_size': self.batch_size}

        with open(self.fullfilepath + '/astroNN_model_parameter.json', 'w') as f:
            json.dump(data, f, indent=4, sort_keys=True)

    def train(self, input_data, labels):
        # Call the checklist to create astroNN folder and save parameters
        self.pre_training_checklist_child(input_data, labels)

        reduce_lr = ReduceLROnPlateau(monitor='val_loss', factor=0.5, epsilon=self.reduce_lr_epsilon,
                                      patience=self.reduce_lr_patience, min_lr=self.reduce_lr_min, mode='min',
                                      verbose=2)

        early_stopping = EarlyStopping(monitor='val_loss', min_delta=self.early_stopping_min_delta,
                                       patience=self.early_stopping_patience, verbose=2, mode='min')

        self.virtual_cvslogger = VirutalCSVLogger()

        self.__callbacks = [reduce_lr, self.virtual_cvslogger]

        if self.callbacks is not None:
            self.__callbacks.append(self.callbacks)

        self.history = self.keras_model.fit_generator(generator=self.training_generator,
                                                      steps_per_epoch=self.num_train // self.batch_size,
                                                      validation_data=self.validation_generator,
                                                      validation_steps=self.num_train // self.batch_size,
                                                      epochs=self.max_epochs, verbose=self.verbose,
                                                      workers=os.cpu_count(),
                                                      callbacks=self.__callbacks,
                                                      use_multiprocessing=MULTIPROCESS_FLAG)

        if self.autosave is True:
            # Call the post training checklist to save parameters
            self.save()

        return None
