# Copyright 2015 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""A binary to train CIFAR-10 using a single GPU."""

import sys
from datetime import datetime
import os.path
import time
import math

import numpy as np
import tensorflow as tf
import vgg
from inputs import cifar10

BATCH_SIZE = 128
STEP_PER_EPOCH = math.ceil(cifar10.NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN /
                           BATCH_SIZE)
MAX_EPOCH = 300
MAX_STEPS = STEP_PER_EPOCH * MAX_EPOCH

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = CURRENT_DIR + "/log"


def keep_prob_decay(validation_accuracy,
                    keep_prob,
                    min_keep_prob,
                    global_step,
                    decay_steps,
                    decay_rate,
                    name=None):
    """ Decay keep_prob until it reaches min_keep_prob.
    The update rule is: max(min_keep_prob, keep_prob - floor(global_step / decay_step))
    where decay_step  =
    """
    if global_step is None:
        raise ValueError("global_step is required for keep_prob_decay")

    with tf.name_scope(
            name, "KeepProbDecay",
        [keep_prob, global_step, decay_steps, decay_rate]) as name:
        keep_prob = tf.convert_to_tensor(
            keep_prob, name="keep_prob", dtype=tf.float32)
        min_keep_prob = tf.convert_to_tensor(
            min_keep_prob, name="min_keep_prob", dtype=tf.float32)
        global_step = tf.cast(global_step, dtype=tf.float32)
        decay_steps = tf.cast(decay_steps, dtype=tf.float32)
        decay_rate = tf.cast(decay_rate, dtype=tf.float32)
        # TODO: define decay_step in function of past validation accuracies
        with tf.control_dependencies([validation_accuracy]):
            pass
        return tf.maximum(min_keep_prob,
                          keep_prob - tf.floor(global_step / decay_step))


def get_accuracy(validation_log, global_step):
    """Run Eval once.
    Args:
        validation_log: summary writer
        global_step: current training step
    """

    with tf.Graph().as_default(), tf.device('/gpu:1'):
        # Get images and labels for CIFAR-10.
        # Use batch_size multiple of train set size and big enough to stay in GPU
        batch_size = 200
        images, labels = cifar10.inputs(eval_data=True, batch_size=batch_size)

        # Build a Graph that computes the logits predictions from the
        # inference model.
        _, logits = vgg.get_model(images, train_phase=False)

        # Calculate predictions.
        top_k_op = tf.nn.in_top_k(logits, labels, 1)

        accuracy_value_ = tf.placeholder(tf.float32, shape=[])
        accuracy_summary = tf.scalar_summary('accuracy', accuracy_value_)

        saver = tf.train.Saver()
        accuracy = 0.0
        with tf.Session(config=tf.ConfigProto(
                allow_soft_placement=True)) as sess:
            ckpt = tf.train.get_checkpoint_state(LOG_DIR)
            if ckpt and ckpt.model_checkpoint_path:
                # Restores from checkpoint
                saver.restore(sess, ckpt.model_checkpoint_path)
            else:
                print('No checkpoint file found')
                return

            # Start the queue runners.
            coord = tf.train.Coordinator()
            try:
                threads = []
                for qr in tf.get_collection(tf.GraphKeys.QUEUE_RUNNERS):
                    threads.extend(
                        qr.create_threads(
                            sess, coord=coord, daemon=True, start=True))

                num_iter = int(
                    math.ceil(cifar10.NUM_EXAMPLES_PER_EPOCH_FOR_EVAL /
                              batch_size))
                true_count = 0  # Counts the number of correct predictions.
                total_sample_count = num_iter * batch_size
                step = 0
                while step < num_iter and not coord.should_stop():
                    predictions = sess.run([top_k_op])
                    true_count += np.sum(predictions)
                    step += 1

                accuracy = true_count / total_sample_count
                print('%s: validation accuracy = %.3f' %
                      (datetime.now(), accuracy))

                validation_log.add_summary(
                    sess.run(accuracy_summary,
                             feed_dict={accuracy_value_: accuracy}),
                    global_step=global_step)
                validation_log.flush()

            except Exception as e:  # pylint: disable=broad-except
                coord.request_stop(e)

            coord.request_stop()
            coord.join(threads, stop_grace_period_secs=10)
        return accuracy


def train():
    """Train CIFAR-10 for a number of steps."""
    with tf.Graph().as_default(), tf.device('/gpu:0'):
        global_step = tf.Variable(0, trainable=False)

        # Get images and labels for CIFAR-10.
        images, labels = cifar10.distorted_inputs(BATCH_SIZE)

        # Build a Graph that computes the logits predictions from the
        # inference model.
        keep_prob_, logits = vgg.get_model(images, train_phase=True)

        # Calculate loss.
        loss_summary, loss = vgg.loss(logits, labels)

        # Build a Graph that trains the model with one batch of examples and
        # updates the model parameters.
        learning_rate_summary, train_op = vgg.train(loss, global_step)

        # Create a saver.
        saver = tf.train.Saver(tf.trainable_variables() + [global_step])

        # Train accuracy ops
        top_k_op = tf.nn.in_top_k(logits, labels, 1)
        accuracy = tf.reduce_mean(tf.cast(top_k_op, tf.float32))
        accuracy_summary = tf.scalar_summary('accuracy', accuracy)

        # merge loss_summary and learning_rate_summary
        # these 2 ops gets executed every iteration
        every_step_summaries = tf.merge_summary(
            [learning_rate_summary, loss_summary])

        # Build an initialization operation to run below.
        init = tf.initialize_all_variables()

        # Start running operations on the Graph.
        with tf.Session(config=tf.ConfigProto(
                allow_soft_placement=True)) as sess:
            sess.run(init)

            # Start the queue runners.
            tf.train.start_queue_runners(sess=sess)
            train_log = tf.train.SummaryWriter(LOG_DIR + "/train", sess.graph)
            validation_log = tf.train.SummaryWriter(LOG_DIR + "/validation",
                                                    sess.graph)

            # Extract previous global step value
            old_gs = sess.run(global_step)

            # Restart from where we were
            for step in range(old_gs, MAX_STEPS):
                start_time = time.time()
                _, loss_value, summary_lines = sess.run(
                    [train_op, loss, every_step_summaries],
                    feed_dict={keep_prob_: 1.0})
                duration = time.time() - start_time

                assert not np.isnan(
                    loss_value), 'Model diverged with loss = NaN'

                # update logs every 10 iterations
                if step % 10 == 0:
                    num_examples_per_step = BATCH_SIZE
                    examples_per_sec = num_examples_per_step / duration
                    sec_per_batch = float(duration)

                    format_str = (
                        '%s: step %d, loss = %.2f (%.1f examples/sec; %.3f '
                        'sec/batch)')
                    print(format_str % (datetime.now(), step, loss_value,
                                        examples_per_sec, sec_per_batch))
                    # log loss value
                    train_log.add_summary(summary_lines, global_step=step)

                # Save the model checkpoint at the end of every epoch
                # evaluate train and validation performance
                if (step > 0 and
                        step % STEP_PER_EPOCH == 0) or (step + 1) == MAX_STEPS:
                    checkpoint_path = os.path.join(LOG_DIR, 'model.ckpt')
                    saver.save(sess, checkpoint_path, global_step=step)

                    # validation accuracy
                    validation_accuracy = get_accuracy(
                        validation_log, global_step=step)
                    # train accuracy
                    train_accuracy, summary_line = sess.run(
                        [accuracy, accuracy_summary])
                    train_log.add_summary(summary_line, global_step=step)
                    print('%s: train accuracy = %.3f' %
                          (datetime.now(), train_accuracy))


def main():
    cifar10.maybe_download_and_extract()
    if tf.gfile.Exists(LOG_DIR):
        tf.gfile.DeleteRecursively(LOG_DIR)
    tf.gfile.MakeDirs(LOG_DIR)
    train()
    return 0


if __name__ == '__main__':
    sys.exit(main())
