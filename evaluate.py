#Copyright (C) 2016 Paolo Galeone <nessuno@nerdz.eu>
# Based on Tensorflow cifar10_train.py file
# https://github.com/tensorflow/tensorflow/blob/r0.11/tensorflow/models/image/cifar10/cifar10_train.py
#
#This Source Code Form is subject to the terms of the Mozilla Public
#License, v. 2.0. If a copy of the MPL was not distributed with this
#file, you can obtain one at http://mozilla.org/MPL/2.0/.
#Exhibit B is not attached; this software is compatible with the
#licenses expressed under Section 1.12 of the MPL v2.
""" Evaluate the model """

from datetime import datetime
import math

import tensorflow as tf
from inputs.utils import InputType
from models.utils import variables_to_restore
from models.interfaces.Autoencoder import Autoencoder
from models.interfaces.Classifier import Classifier
from CLIArgs import CLIArgs


def accuracy(checkpoint_path, model, dataset, input_type, batch_size=200):
    """
    Reads the checkpoint and use it to evaluate the model
    Args:
        checkpoint_path: checkpoint folder
        model: python package containing the model saved
        dataset: python package containing the dataset to use
        input_type: InputType enum, the input type of the input examples
        batch_size: batch size for the evaluation in batches
    Returns:
        average_accuracy: the average accuracy
    """
    InputType.check(input_type)

    # Get images and labels from the dataset
    with tf.device('/cpu:0'):
        images, labels = dataset.inputs(
            input_type=input_type, batch_size=batch_size)

    labels = tf.squeeze(labels)

    # Build a Graph that computes the predictions from the inference model.
    _, predictions = model.get(images, dataset.num_classes(), train_phase=False)

    # Calculate correct predictions.
    correct_predictions = tf.reduce_sum(
        tf.cast(tf.nn.in_top_k(predictions, labels, 1), tf.int32))

    saver = tf.train.Saver(variables_to_restore())
    accuracy_value = 0.0
    with tf.Session(config=tf.ConfigProto(allow_soft_placement=True)) as sess:
        ckpt = tf.train.get_checkpoint_state(checkpoint_path)
        if ckpt and ckpt.model_checkpoint_path:
            # Restores from checkpoint
            saver.restore(sess, ckpt.model_checkpoint_path)
        else:
            print('[!] No checkpoint file found')
            return

        # Start the queue runners.
        coord = tf.train.Coordinator()
        try:
            threads = []
            for queue_runner in tf.get_collection(tf.GraphKeys.QUEUE_RUNNERS):
                threads.extend(
                    queue_runner.create_threads(
                        sess, coord=coord, daemon=True, start=True))

            num_iter = int(
                math.ceil(dataset.num_examples(input_type) / batch_size))
            # Counts the number of correct predictions.
            true_count = 0
            total_sample_count = num_iter * batch_size
            step = 0
            while step < num_iter and not coord.should_stop():
                true_count += sess.run(correct_predictions)
                step += 1

            accuracy_value = true_count / total_sample_count
        except Exception as exc:
            coord.request_stop(exc)
        finally:
            coord.request_stop()

        coord.join(threads)
    return accuracy_value


def error(checkpoint_path, model, dataset, input_type, batch_size=200):
    """
    Reads the checkpoint and use it to evaluate the model
    Args:
        checkpoint_path: checkpoint folder
        model: python package containing the model saved
        dataset: python package containing the dataset to use
        input_type: InputType enum, the input type of the input examples
        batch_size: batch size for the evaluation in batches
    Returns:
        average_error: the average error
    """
    InputType.check(input_type)

    # Get images and labels from the dataset
    with tf.device('/cpu:0'):
        images, _ = dataset.inputs(input_type=input_type, batch_size=batch_size)

    # Build a Graph that computes the reconstructions from the inference model.
    _, reconstructions = model.get(images, train_phase=False, l2_penalty=0.0)

    # Calculate loss.
    loss = model.loss(reconstructions, images)

    saver = tf.train.Saver(variables_to_restore())
    with tf.Session(config=tf.ConfigProto(allow_soft_placement=True)) as sess:
        ckpt = tf.train.get_checkpoint_state(checkpoint_path)
        if ckpt and ckpt.model_checkpoint_path:
            # Restores from checkpoint
            saver.restore(sess, ckpt.model_checkpoint_path)
        else:
            print('[!] No checkpoint file found')
            return

        # Start the queue runners.
        coord = tf.train.Coordinator()
        try:
            threads = []
            for queue_runner in tf.get_collection(tf.GraphKeys.QUEUE_RUNNERS):
                threads.extend(
                    queue_runner.create_threads(
                        sess, coord=coord, daemon=True, start=True))

            num_iter = int(
                math.ceil(dataset.num_examples(input_type) / batch_size))
            step = 0
            average_error = 0.0
            while step < num_iter and not coord.should_stop():
                error_value = sess.run(loss)
                step += 1
                average_error += error_value
            average_error /= step
        except Exception as exc:
            coord.request_stop(exc)
        finally:
            coord.request_stop()

        coord.join(threads)
    return average_error


def iou(checkpoint_path, model, dataset, input_type, batch_size=200):
    """
    Reads the checkpoint and use it to evaluate the model
    Args:
        checkpoint_path: checkpoint folder
        model: python package containing the model saved
        dataset: python package containing the dataset to use
        input_type: InputType enum, the input type of the input examples
        batch_size: batch size for the evaluation in batches
    Returns:
        average_accuracy: the average accuracy
    """
    InputType.check(input_type)

    #TODO
    with tf.variable_scope('iou'):
        ymin_orig = real_coordinates[:, 0]
        xmin_orig = real_coordinates[:, 1]
        ymax_orig = real_coordinates[:, 2]
        xmax_orig = real_coordinates[:, 3]
        area_orig = (ymax_orig - ymin_orig) * (xmax_orig - xmin_orig)

        ymin = coordinates[:, 0]
        xmin = coordinates[:, 1]
        ymax = coordinates[:, 2]
        xmax = coordinates[:, 3]
        area_pred = (ymax - ymin) * (xmax - xmin)

        intersection_ymin = tf.maximum(ymin, ymin_orig)
        intersection_xmin = tf.maximum(xmin, xmin_orig)
        intersection_ymax = tf.minimum(ymax, ymax_orig)
        intersection_xmax = tf.minimum(xmax, xmax_orig)

        intersection_area = tf.maximum(
            intersection_ymax - intersection_ymin,
            tf.zeros_like(intersection_ymax)) * tf.maximum(
                intersection_xmax - intersection_xmin,
                tf.zeros_like(intersection_ymax))

        iou = tf.reduce_mean(intersection_area /
                             (area_orig + area_pred - intersection_area))


if __name__ == '__main__':
    ARGS, MODEL, DATASET = CLIArgs(
        description="Evaluate the model").parse_eval()

    INPUT_TYPE = InputType.test if ARGS.test else InputType.validation
    # models need to be instantiated in "train mode" in order to define
    # the complete graph. Then the evaluation reinstantiate the model but
    # in "test" mode, reusing the previosly defined variable.
    if isinstance(MODEL, Classifier):
        with tf.device('/cpu:0'):
            IMAGES, _ = DATASET.inputs(input_type=INPUT_TYPE, batch_size=1)

        with tf.device(ARGS.eval_device):
            _ = MODEL.get(IMAGES, DATASET.num_classes(), train_phase=True)
            print('{}: {} accuracy = {:.3f}'.format(
                datetime.now(), 'test' if ARGS.test else 'validation',
                accuracy(ARGS.checkpoint_path, MODEL, DATASET, INPUT_TYPE)))

    if isinstance(MODEL, Autoencoder):
        with tf.device('/cpu:0'):
            IMAGES, _ = DATASET.inputs(input_type=INPUT_TYPE, batch_size=1)
        with tf.device(ARGS.eval_device):
            _ = MODEL.get(IMAGES, train_phase=True)
            print('{}: {} error = {:.3f}'.format(
                datetime.now(), 'test' if ARGS.test else 'validation',
                error(ARGS.checkpoint_path, MODEL, DATASET, INPUT_TYPE)))
