# -*- coding: utf-8 -*-
"""DQN_Reload.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1gwmbsO4lnbxpxRYfXgY-qWwiFFECHeQh
"""

from google.colab import drive
drive.mount('/content/gdrive')

from tensorflow.python.client import device_lib
device_lib.list_local_devices()

import gym
from gym import spaces
from gym.wrappers import TimeLimit
import tensorflow as tf
from tensorflow.keras.optimizers import RMSprop
from tensorflow.keras.losses import Huber
import numpy as np
from timeit import default_timer as timer
import os
os.environ.setdefault('PATH', '')
import cv2
cv2.ocl.setUseOpenCL(False)
import dill as pickle
from collections import deque
import random

def read_pickle(file_path):
    with open(file_path, 'rb') as f:
        data = pickle.load(f)
    return data

held_out_memory = read_pickle('/content/gdrive/My Drive/DQN/DQN_Pong/Memory/held_out_memory.pickle')
checkpoint = read_pickle('/content/gdrive/My Drive/DQN/DQN_Pong/Checkpoint/check_point_147.0.pickle')
model_params = checkpoint['params']
model_optimizer = checkpoint['optimizer']
model_epsilon = checkpoint['epsilon']

print('held_out_memory type:', type(held_out_memory))
print('model_optimizer type:', type(model_optimizer))
print('model_optimizer:', model_optimizer)
print('model_epsilon type:', type(model_epsilon))
print('model_epsilon:', model_epsilon)

class FireResetEnv(gym.Wrapper):
    def __init__(self, env):
        """Take action on reset for environments that are fixed until firing."""
        gym.Wrapper.__init__(self, env)
        assert env.unwrapped.get_action_meanings()[1] == 'FIRE'
        assert len(env.unwrapped.get_action_meanings()) >= 3

    def reset(self, **kwargs):
        self.env.reset(**kwargs)
        obs, _, done, _ = self.env.step(1)
        if done:
            self.env.reset(**kwargs)
        obs, _, done, _ = self.env.step(2)
        if done:
            self.env.reset(**kwargs)
        return obs

    def step(self, ac):
        return self.env.step(ac)

class EpisodicLifeEnv(gym.Wrapper):
    def __init__(self, env):
        """Make end-of-life == end-of-episode, but only reset on true game over.
        Done by DeepMind for the DQN and co. since it helps value estimation.
        """
        gym.Wrapper.__init__(self, env)
        self.lives = 0
        self.was_real_done  = True

    def step(self, action):
        obs, reward, done, info = self.env.step(action)
        self.was_real_done = done
        # check current lives, make loss of life terminal,
        # then update lives to handle bonus lives
        lives = self.env.unwrapped.ale.lives()
        if lives < self.lives and lives > 0:
            # for Qbert sometimes we stay in lives == 0 condition for a few frames
            # so it's important to keep lives > 0, so that we only reset once
            # the environment advertises done.
            done = True
        self.lives = lives
        return obs, reward, done, info

    def reset(self, **kwargs):
        """Reset only when lives are exhausted.
        This way all states are still reachable even though lives are episodic,
        and the learner need not know about any of this behind-the-scenes.
        """
        if self.was_real_done:
            obs = self.env.reset(**kwargs)
        else:
            # no-op step to advance from terminal/lost life state
            obs, _, _, _ = self.env.step(0)
        self.lives = self.env.unwrapped.ale.lives()
        return obs
class NoopResetEnv(gym.Wrapper):
    def __init__(self, env, noop_max=30):
        """Sample initial states by taking random number of no-ops on reset.
        No-op is assumed to be action 0.
        """
        gym.Wrapper.__init__(self, env)
        self.noop_max = noop_max
        self.override_num_noops = None
        self.noop_action = 0
        assert env.unwrapped.get_action_meanings()[0] == 'NOOP'

    def reset(self, **kwargs):
        """ Do no-op action for a number of steps in [1, noop_max]."""
        self.env.reset(**kwargs)
        if self.override_num_noops is not None:
            noops = self.override_num_noops
        else:
            noops = self.unwrapped.np_random.randint(1, self.noop_max + 1) #pylint: disable=E1101
        assert noops > 0
        obs = None
        for _ in range(noops):
            obs, _, done, _ = self.env.step(self.noop_action)
            if done:
                obs = self.env.reset(**kwargs)
        return obs

    def step(self, ac):
        return self.env.step(ac)
class MaxAndSkipEnv(gym.Wrapper):
    def __init__(self, env, skip=4):
        """Return only every `skip`-th frame"""
        gym.Wrapper.__init__(self, env)
        # most recent raw observations (for max pooling across time steps)
        self._obs_buffer = np.zeros((2,)+env.observation_space.shape, dtype=np.uint8)
        self._skip       = skip
        if skip > 1:
            assert 'NoFrameskip' in env.spec.id, 'disable frame-skipping in the original env. for more than one' \
                                                 ' frame-skip as it will be done by the wrapper'

    def step(self, action):
        """Repeat action, sum reward, and max over last observations."""
        total_reward = 0.0
        done = None
        for i in range(self._skip):
            obs, reward, done, info = self.env.step(action)
            if i == self._skip - 2: self._obs_buffer[0] = obs
            if i == self._skip - 1: self._obs_buffer[1] = obs
            total_reward += reward
            if done:
                break
        # Note that the observation on the done=True frame
        # doesn't matter
        max_frame = self._obs_buffer.max(axis=0)

        return max_frame, total_reward, done, info

    def reset(self, **kwargs):
        return self.env.reset(**kwargs)
class ClipRewardEnv(gym.RewardWrapper):
    def __init__(self, env):
        gym.RewardWrapper.__init__(self, env)

    def reward(self, reward):
        """Bin reward to {+1, 0, -1} by its sign."""
        return np.sign(reward)


class WarpFrame(gym.ObservationWrapper):
    def __init__(self, env, width=84, height=84, grayscale=True, dict_space_key=None):
        """
        Warp frames to 84x84 as done in the Nature paper and later work.
        If the environment uses dictionary observations, `dict_space_key` can be specified which indicates which
        observation should be warped.
        """
        super().__init__(env)
        self._width = width
        self._height = height
        self._grayscale = grayscale
        self._key = dict_space_key
        if self._grayscale:
            num_colors = 1
        else:
            num_colors = 3

        new_space = gym.spaces.Box(
            low=0,
            high=255,
            shape=(self._height, self._width, num_colors),
            dtype=np.uint8,
        )
        if self._key is None:
            original_space = self.observation_space
            self.observation_space = new_space
        else:
            original_space = self.observation_space.spaces[self._key]
            self.observation_space.spaces[self._key] = new_space
        assert original_space.dtype == np.uint8 and len(original_space.shape) == 3

    def observation(self, obs):
        if self._key is None:
            frame = obs
        else:
            frame = obs[self._key]

        if self._grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        frame = cv2.resize(
            frame, (self._width, self._height), interpolation=cv2.INTER_AREA
        )
        if self._grayscale:
            frame = np.expand_dims(frame, -1)

        if self._key is None:
            obs = frame
        else:
            obs = obs.copy()
            obs[self._key] = frame
        return obs

class ScaledFloatFrame(gym.ObservationWrapper):
    def __init__(self, env):
        gym.ObservationWrapper.__init__(self, env)
        self.observation_space = gym.spaces.Box(low=0, high=1, shape=env.observation_space.shape, dtype=np.float32)

    def observation(self, observation):
        # careful! This undoes the memory optimization, use
        # with smaller replay buffers only.
        return np.array(observation).astype(np.float32) / 255.0

class FrameStack(gym.Wrapper):
    def __init__(self, env, k):
        """Stack k last frames.
        Returns lazy array, which is much more memory efficient.
        See Also
        --------
        baselines.common.atari_wrappers.LazyFrames
        """
        gym.Wrapper.__init__(self, env)
        self.k = k
        self.frames = deque([], maxlen=k)
        shp = env.observation_space.shape
        self.observation_space = spaces.Box(low=0, high=255, shape=(shp[:-1] + (shp[-1] * k,)), dtype=env.observation_space.dtype)

    def reset(self):
        ob = self.env.reset()
        for _ in range(self.k):
            self.frames.append(ob)
        return self._get_ob()

    def step(self, action):
        ob, reward, done, info = self.env.step(action)
        self.frames.append(ob)
        return self._get_ob(), reward, done, info

    def _get_ob(self):
        assert len(self.frames) == self.k
        return LazyFrames(list(self.frames))


class LazyFrames(object):
    def __init__(self, frames):
        """This object ensures that common frames between the observations are only stored once.
        It exists purely to optimize memory usage which can be huge for DQN's 1M frames replay
        buffers.
        This object should only be converted to numpy array before being passed to the model.
        You'd not believe how complex the previous solution was."""
        self._frames = frames
        self._out = None

    def _force(self):
        if self._out is None:
            self._out = np.concatenate(self._frames, axis=-1)
            self._frames = None
        return self._out

    def __array__(self, dtype=None):
        out = self._force()
        if dtype is not None:
            out = out.astype(dtype)
        return out

    def __len__(self):
        return len(self._force())

    def __getitem__(self, i):
        return self._force()[i]

    def count(self):
        frames = self._force()
        return frames.shape[frames.ndim - 1]

    def frame(self, i):
        return self._force()[..., i]
def wrap_deepmind(env, episode_life=True, clip_rewards=True, frame_stack=True, scale=False):
    """Configure environment for DeepMind-style Atari.
    """
    if episode_life:
        env = EpisodicLifeEnv(env)
    if 'FIRE' in env.unwrapped.get_action_meanings():
        env = FireResetEnv(env)
    env = WarpFrame(env)
    if scale:
        env = ScaledFloatFrame(env)
    if clip_rewards:
        env = ClipRewardEnv(env)
    if frame_stack:
        env = FrameStack(env, 4)
    return env
def make_atari(env_id, max_episode_steps=None):
    env = gym.make(env_id)
    env = NoopResetEnv(env, noop_max=30)
    env = MaxAndSkipEnv(env, skip=4)
    if max_episode_steps is not None:
        env = TimeLimit(env, max_episode_steps=max_episode_steps)
    env = wrap_deepmind(env)
    return env

def save_file(file_name, my_list):
    with open(file_name, 'w') as f:
        for single_element in my_list:
            f.write(str(single_element))
            f.write('\n')
            
def save_pickle(file_name, data):
    with open(file_name, 'wb') as f:
        pickle.dump(data, f)

def sample_action(policy, action_size):
    all_actions = np.arange(action_size)
    return np.random.choice(all_actions, p=policy)

def average_action_value_metric(agent):
    model_updating_predict = agent.model_updating.predict(agent.held_out_memory)
    max_value_batch = np.amax(model_updating_predict, axis=1)
    average_action_value = np.average(max_value_batch)
    return average_action_value

class Conv_Layer:
    def __init__(self, num_input_channels, num_filters, filter_shape, filter_stride, name, padding='VALID'):
        self.name = name
        self.filter_stride = filter_stride
        self.padding = padding
        self.conv_filt_shape = (filter_shape, filter_shape, num_input_channels, num_filters)
        self.initializer = tf.keras.initializers.HeNormal()
        self.weights = tf.Variable(self.initializer(shape=self.conv_filt_shape), name=self.name+'_W')
        self.bias = tf.Variable(self.initializer(shape=(1, num_filters)), name=self.name+'_b')
    
    def compute(self, input_data):
        # setup the convolutional layer operation
        output = tf.nn.conv2d(input_data, self.weights, [1, self.filter_stride, self.filter_stride, 1], padding=self.padding)
        # add the bias
        output += self.bias

        # apply a ReLU non-linear activation
        output = tf.nn.relu(output)

        return output


class Dense_Layer:
    def __init__(self, num_input_neurons, num_output_neurons, name):
        self.name = name
        self.initializer = tf.keras.initializers.HeNormal()
        self.weights = tf.Variable(self.initializer(shape=(num_input_neurons, num_output_neurons)), name=name+'_W')
        self.bias = tf.Variable(self.initializer(shape=(1, num_output_neurons)), name=name+'_b')
    
    def compute(self, input_data):
        output = tf.matmul(input_data, self.weights) + self.bias
        return output

        
class NN_DQN:
    def __init__(self, num_actions_env, nn_name):
        self.layer_1 = Conv_Layer(4, 32, 8, 4, name=nn_name+'_conv_1')
        self.layer_2 = Conv_Layer(32, 64, 4, 2, name=nn_name+'_conv_2')
        self.layer_3 = Conv_Layer(64, 64, 3, 1, name=nn_name+'_conv_3')
        self.layer_4 = Dense_Layer(7 * 7 * 64, 512, name=nn_name+'_dense_1')
        self.layer_5 = Dense_Layer(512, num_actions_env, name=nn_name+'_output')

    def predict(self, input_data):
        x = self.layer_1.compute(input_data)
        x = self.layer_2.compute(x)
        x = self.layer_3.compute(x)
        x = tf.reshape(x, [-1, 7 * 7 * 64])
        x = self.layer_4.compute(x)
        x = tf.nn.relu(x)
        x = self.layer_5.compute(x)
        return x
    
    def calculate_loss(self, targets, predicts):
        h = tf.keras.losses.Huber()
        loss = tf.reduce_mean(h(targets, predicts))
        return loss

    def set_parameters(self, params):
        self.layer_1.weights.assign(params[0].numpy())
        self.layer_1.bias.assign(params[1].numpy())
        self.layer_2.weights.assign(params[2].numpy())
        self.layer_2.bias.assign(params[3].numpy())  
        self.layer_3.weights.assign(params[4].numpy())
        self.layer_3.bias.assign(params[5].numpy())
        self.layer_4.weights.assign(params[6].numpy())
        self.layer_4.bias.assign(params[7].numpy())
        self.layer_5.weights.assign(params[8].numpy())
        self.layer_5.bias.assign(params[9].numpy())

class DqnAgent:
    #### set the hyperparameters ####
    def __init__(self, env, action_size):
        #### initialize the model ####
        self.model_updating = NN_DQN(action_size, 'updatingNN')
        self.model_fix = NN_DQN(action_size, 'targetNN')
        #### load the weights ####
        self.model_updating.set_parameters(model_params)
        self.model_fix.set_parameters(model_params)
        #### load the optimizer ####
        self.optimizer = model_optimizer
        #### load the held_out_memory ####
        self.held_out_memory = held_out_memory
        #### load the epsilon ####
        self.epsilon = model_epsilon  
        ####
        self.epsilon_initial = 1.0  ## starting exploration rate; 1.0 in the paper
        self.epsilon_final = 0.02   ## ending exploration rate in DQN paper; 0.1 in DQN paper
        self.epsilon_decay_frames = 100000   ## 1,000,000 in the paper
        self.epsilon_decay_rate = (self.epsilon_initial - self.epsilon_final) / self.epsilon_decay_frames
        self.replay_memory = deque(maxlen=100000) ## 1,000,000 in the paper
        self.replay_start_size = 50 ## replay start size; 50,000 in the paper
        self.target_update_steps = 10 ## target network update frequency; 10,000 in the paper
        self.checkpoint = 10
        self.gamma = 0.99   ## discount factor; 0.99 in the paper
        #####

    def save(self, file_name):
        model_dic = {
               'params': [self.model_updating.layer_1.weights, self.model_updating.layer_1.bias,
                          self.model_updating.layer_2.weights, self.model_updating.layer_2.bias,
                          self.model_updating.layer_3.weights, self.model_updating.layer_3.bias,
                          self.model_updating.layer_4.weights, self.model_updating.layer_4.bias,
                          self.model_updating.layer_5.weights, self.model_updating.layer_5.bias],
               'optimizer': self.optimizer,
               'epsilon': self.epsilon
               }
        save_pickle(file_name, model_dic)
        
    def memorize(self, state, action, reward, next_state, done):
        self.replay_memory.append((state, action, reward, next_state, done))

    def update_model(self):
        self.model_fix.set_parameters([self.model_updating.layer_1.weights, self.model_updating.layer_1.bias,
                                       self.model_updating.layer_2.weights, self.model_updating.layer_2.bias,
                                       self.model_updating.layer_3.weights, self.model_updating.layer_3.bias,
                                       self.model_updating.layer_4.weights, self.model_updating.layer_4.bias,
                                       self.model_updating.layer_5.weights, self.model_updating.layer_5.bias])

def pre_play(env, action_size, agent):
    play_steps = 0
    while play_steps < agent.replay_start_size:
        #### start/restart the game ####
        state = env.reset()
        state = tf.Variable(state, dtype=tf.float32)
        state = tf.reshape(state, [-1, 84, 84, 4])
        done = False

        while not done:
            play_steps += 1
            #### select action according to epsilon-greedy ####
            max_action = np.argmax(agent.model_updating.predict(state), axis=1)
            policy = agent.epsilon * (np.ones(action_size)/action_size)
            policy[max_action] = policy[max_action] + (1 - agent.epsilon)
            action = sample_action(policy, action_size)
            #### play and observe the result ####
            next_state, reward, done, _ = env.step(action)
            #### store experiences into the replay memory ####
            next_state = tf.Variable(next_state, dtype=tf.float32)
            next_state = tf.reshape(next_state, [-1, 84, 84, 4])
            agent.memorize(state, action, reward, next_state, done)
            ####
            state = next_state

def play(env, action_size, agent):
    total_updated_number = 0
    model_update_tracing = 0
    checkpoint_tracing = 0
    average_action_value_record = []
    while True:
        #### start/restart the game ####
        state = env.reset()
        state = tf.Variable(state, dtype=tf.float32)
        state = tf.reshape(state, [-1, 84, 84, 4])
        done = False

        while not done:
            total_updated_number += 1
            #### select action according to epsilon-greedy ####
            max_action = np.argmax(agent.model_updating.predict(state), axis=1)
            policy = agent.epsilon * (np.ones(action_size)/action_size)
            policy[max_action] = policy[max_action] + (1 - agent.epsilon)
            action = sample_action(policy, action_size)
            #### play and observe the result ####
            next_state, reward, done, _ = env.step(action)
            #### store experiences into the replay memory ####
            next_state = tf.Variable(next_state, dtype=tf.float32)
            next_state = tf.reshape(next_state, [-1, 84, 84, 4])
            agent.memorize(state, action, reward, next_state, done)
            ####
            state = next_state

            #### train the model using replay memory ####
            state_batch, action_batch, reward_batch, next_state_batch, done_batch = [], [], [], [], []
            sample_batch = random.sample(agent.replay_memory, 32)

            for sample in sample_batch:
                state_batch.append(sample[0])
                action_batch.append(sample[1])
                reward_batch.append(sample[2])
                next_state_batch.append(sample[3])
                done_batch.append(sample[4])

            state_batch = tf.concat(state_batch, 0)
            reward_batch = np.array(reward_batch).reshape((-1, 1))
            next_state_batch = tf.concat(next_state_batch, 0)
            done_batch = np.array(done_batch).astype(int).reshape((-1, 1))
            done_batch ^= 1

            rows = np.arange(32)
            one_hot_ones = np.ones((32, action_size))
            one_hot_ones[rows, action_batch] = 0
            one_hot_zeros = np.zeros((32, action_size))
            one_hot_zeros[rows, action_batch] = 1

            model_fix_predict = agent.model_fix.predict(next_state_batch)
            max_value_batch = np.amax(model_fix_predict, axis=1, keepdims=True)
            target_batch = reward_batch + done_batch * max_value_batch * agent.gamma

            #### train the network ####
            with tf.GradientTape() as tape:
                #### get the predicted value batch ####
                model_updating_predict = agent.model_updating.predict(state_batch)
                #### get the target value batch ####
                target = tf.Variable(one_hot_zeros * target_batch + one_hot_ones * model_updating_predict)
                #### calculate the loss ####
                loss = agent.model_updating.calculate_loss(target, model_updating_predict)

            #### calculate the gradient ####
            gradients = tape.gradient(loss, [agent.model_updating.layer_1.weights, agent.model_updating.layer_1.bias,
                                             agent.model_updating.layer_2.weights, agent.model_updating.layer_2.bias,
                                             agent.model_updating.layer_3.weights, agent.model_updating.layer_3.bias,
                                             agent.model_updating.layer_4.weights, agent.model_updating.layer_4.bias,
                                             agent.model_updating.layer_5.weights, agent.model_updating.layer_5.bias])
            
            #### update the parameters ####
            agent.optimizer.apply_gradients(zip(gradients, [agent.model_updating.layer_1.weights, agent.model_updating.layer_1.bias,
                                                            agent.model_updating.layer_2.weights, agent.model_updating.layer_2.bias,
                                                            agent.model_updating.layer_3.weights, agent.model_updating.layer_3.bias,
                                                            agent.model_updating.layer_4.weights, agent.model_updating.layer_4.bias,
                                                            agent.model_updating.layer_5.weights, agent.model_updating.layer_5.bias]))

            #### update the target model ####
            model_update_tracing += 1
            if model_update_tracing >= agent.target_update_steps:
                model_update_tracing = 0
                agent.update_model()

            #### metric and checkpoint ####
            checkpoint_tracing += 1
            if checkpoint_tracing == agent.checkpoint:
                checkpoint_tracing = 0
                #### average action value metric ####
                average_action_value = average_action_value_metric(agent)
                average_action_value_record.append(average_action_value)
                save_file('/content/gdrive/My Drive/DQN/DQN_Pong/Metric/average_action_value_record_1.txt', average_action_value_record)
                #### checkpoint ####
                agent.save('/content/gdrive/My Drive/DQN/DQN_Pong/Checkpoint/check_point_{}.pickle'.format(total_updated_number/agent.checkpoint + 147.0))
                print('checkpoint saved')
            
            # #### runtime measure ####
            # end_1 = timer()
            # print('1:', end_1 - start)

            #### decrease the epsilon ####
            if agent.epsilon > agent.epsilon_final:
                agent.epsilon -= agent.epsilon_decay_rate

def main(game_name):
    #### set up the environment and agent ####
    env = make_atari(game_name, max_episode_steps=None)
    action_size = env.action_space.n
    agent = DqnAgent(env, action_size)
    #### preplay ####
    pre_play(env, action_size, agent)
    #### play the game and update the parameters ####
    play(env, action_size, agent)

if __name__ == "__main__":
    #### set the name of game ####
    main('PongNoFrameskip-v4')