import random
import torch
import torch.optim as optim
import torch.nn.functional as F

from DeepRLAgent.VanillaInput.DeepQNetwork import DQN
from DeepRLAgent.ReplayMemory import ReplayMemory, Transition

# from DeepQNetwork import DQN
# from ReplayMemory import ReplayMemory, Transition


from itertools import count
from tqdm import tqdm
import math

from pathlib import Path

from PatternDetectionInCandleStick.Evaluation import Evaluation

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class Train:
    def __init__(self, data_train, data_test, dataset_name, BATCH_SIZE=30, GAMMA=0.7, EPS=0.1, ReplayMemorySize=50,
                 TARGET_UPDATE=5,
                 n_actions=3,
                 n_step=10):
        """
        :param TARGET_UPDATE: Every TARGET_UPDATE iterations, we give the weights of the Policy network to the Target
                                network.
        :param n_step: n in n-step SARSA
        """
        print('Deep RL Agent')
        self.data_train = data_train
        self.data_test = data_test
        self.DATASET_NAME = dataset_name
        self.BATCH_SIZE = BATCH_SIZE
        self.GAMMA = GAMMA
        self.EPS = EPS
        self.ReplayMemorySize = ReplayMemorySize

        self.TARGET_UPDATE = TARGET_UPDATE
        self.n_actions = n_actions
        self.n_step = n_step

        self.policy_net = DQN(data_train.state_size, n_actions).to(device)
        self.target_net = DQN(data_train.state_size, n_actions).to(device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()

        # optimizer = optim.RMSprop(policy_net.parameters())
        self.optimizer = optim.Adam(self.policy_net.parameters())
        self.memory = ReplayMemory(ReplayMemorySize)

        self.train_test_split = True if data_test is not None else False

        self.EPS_START = 0.9
        self.EPS_END = 0.05
        self.EPS_DECAY = 200

        self.steps_done = 0

    def select_action(self, state):
        sample = random.random()

        eps_threshold = self.EPS_END + (self.EPS_START - self.EPS_END) * \
                        math.exp(-1. * self.steps_done / self.EPS_DECAY)
        self.steps_done += 1

        # eps_threshold = self.EPS

        if sample > eps_threshold:
            with torch.no_grad():
                # t.max(1) will return largest column value of each row.
                # second column on max result is index of where max element was
                # found, so we pick action with the larger expected reward.
                # self.policy_net.eval()
                # action = self.policy_net(state).max(1)[1].view(1, 1)
                # self.policy_net.train()
                # return action
                return self.policy_net(state).max(1)[1].view(1, 1)
        else:
            return torch.tensor([[random.randrange(self.n_actions)]], device=device, dtype=torch.long)

    def optimize_model(self):
        if len(self.memory) < self.BATCH_SIZE:
            return
        transitions = self.memory.sample(self.BATCH_SIZE)
        # Transpose the batch (see https://stackoverflow.com/a/19343/3343043 for
        # detailed explanation). This converts batch-array of Transitions
        # to Transition of batch-arrays.
        batch = Transition(*zip(*transitions))

        # Compute a mask of non-final states and concatenate the batch elements
        # (a final state would've been the one after which simulation ended)
        non_final_mask = torch.tensor(tuple(map(lambda s: s is not None,
                                                batch.next_state)), device=device, dtype=torch.bool)
        non_final_next_states = torch.cat([s for s in batch.next_state
                                           if s is not None])
        state_batch = torch.cat(batch.state)
        action_batch = torch.cat(batch.action)
        reward_batch = torch.cat(batch.reward)

        # Compute Q(s_t, a) - the model computes Q(s_t), then we select the
        # columns of actions taken. These are the actions which would've been taken
        # for each batch state according to policy_net

        # Using policy-net, we calculate the action-value of the previous actions we have taken before.
        state_action_values = self.policy_net(state_batch).gather(1, action_batch)

        # Compute V(s_{t+1}) for all next states.
        # Expected values of actions for non_final_next_states are computed based
        # on the "older" target_net; selecting their best reward with max(1)[0].
        # This is merged based on the mask, such that we'll have either the expected
        # state value or 0 in case the state was final.
        next_state_values = torch.zeros(self.BATCH_SIZE, device=device)
        next_state_values[non_final_mask] = self.target_net(non_final_next_states).max(1)[0].detach()
        # Compute the expected Q values
        expected_state_action_values = (next_state_values * (self.GAMMA ** self.n_step)) + reward_batch

        # Compute Huber loss
        loss = F.smooth_l1_loss(state_action_values, expected_state_action_values.unsqueeze(1))

        # Optimize the model
        self.optimizer.zero_grad()
        loss.backward()
        for param in self.policy_net.parameters():
            param.grad.data.clamp_(-1, 1)
        self.optimizer.step()

    def train(self, num_episodes=50):
        for i_episode in tqdm(range(num_episodes)):
            # Initialize the environment and state
            self.data_train.reset()
            state = torch.tensor([self.data_train.get_current_state()], dtype=torch.float, device=device)
            for t in count():
                # Select and perform an action
                action = self.select_action(state)
                done, reward, next_state = self.data_train.step(action.item())

                reward = torch.tensor([reward], dtype=torch.float, device=device)

                if next_state is not None:
                    next_state = torch.tensor([next_state], dtype=torch.float, device=device)

                # Store the transition in memory
                self.memory.push(state, action, next_state, reward)

                # Move to the next state
                if not done:
                    state = torch.tensor([self.data_train.get_current_state()], dtype=torch.float, device=device)

                # Perform one step of the optimization (on the target network)
                self.optimize_model()
                if done:
                    break
            # Update the target network, copying all weights and biases in DQN
            if i_episode % self.TARGET_UPDATE == 0:
                self.target_net.load_state_dict(self.policy_net.state_dict())

        self.save_model(self.policy_net.state_dict())

        print('Complete')

    def save_model(self, model):

        experiment_num = 1
        import os
        PATH = os.path.join(Path(os.path.abspath(os.path.dirname(__file__))).parent, 'Objects\\DeepRL') + '\\'

        while os.path.exists(
                f'{PATH}{self.DATASET_NAME}; DATA_KIND({self.data_train.data_kind}); DeepRL; TRAIN_TEST_SPLIT({self.train_test_split}); BATCH_SIZE{self.BATCH_SIZE}; GAMMA{self.GAMMA}; EPSILON{self.EPS}; '
                f'REPLAY_MEMORY_SIZE{self.ReplayMemorySize}; C{self.TARGET_UPDATE}; N_SARSA{self.n_step}; '
                f'EXPERIMENT({experiment_num}).pkl'):
            experiment_num += 1

        file_name = f'{PATH}{self.DATASET_NAME}; DATA_KIND({self.data_train.data_kind}); DeepRL; TRAIN_TEST_SPLIT({self.train_test_split}); BATCH_SIZE{self.BATCH_SIZE}; GAMMA{self.GAMMA}; EPSILON{self.EPS}; ' \
                    f'REPLAY_MEMORY_SIZE{self.ReplayMemorySize}; C{self.TARGET_UPDATE}; N_SARSA{self.n_step}; ' \
                    f'EXPERIMENT({experiment_num}).pkl '

        torch.save(model, file_name)
        self.model_file_name = file_name

    def test(self, file_name, action_name, test_type='train'):
        """
        :param file_name: name of the .pkl file to load the model
        :param test_type: test results on train data or test data
        :return:
        """
        if file_name is None:
            file_path = self.model_file_name
        else:
            import os
            file_path = os.path.join(Path(os.path.abspath(os.path.dirname(__file__))).parent,
                                     f'Objects\\DeepRL\\{file_name}')

        data = self.data_train if test_type == 'train' else self.data_test
        test_net = DQN(data.state_size, self.n_actions)
        test_net.load_state_dict(torch.load(file_path))
        test_net.to(device)
        action_list = []
        data.__iter__()

        for batch in data:
            action_batch = test_net(batch).max(1)[1]
            action_list += list(action_batch.cpu().numpy())

        data.make_investment(action_list)

        ev_agent = Evaluation(data.data, action_name, 1000)
        print('Deep RL Agent')
        ev_agent.evaluate()
        return ev_agent


from DataLoader.DataLoader import YahooFinanceDataLoader
from DataLoader.DataAutoPatternExtractionAgent import DataAutoPatternExtractionAgent

BATCH_SIZE = 10
GAMMA = 0.7
# EPS_START = 0.9
# EPS_END = 0.05
# EPS_DECAY = 200
EPS = 0.1
ReplayMemorySize = 20

TARGET_UPDATE = 5
n_actions = 3
n_step = 10  # in n-step SARSA
window_size = 20

# State Mode
state_mode = 1  # OHLC
# state_mode = 2  # OHLC + trend
# state_mode = 3  # OHLC + trend + %body + %upper-shadow + %lower-shadow
# state_mode = 4  # trend + %body + %upper-shadow + %lower-shadow
# state_mode = 5  # window with k candles inside + the trend of those candles

# BTC-USD

DATASET_NAME = 'BTC-USD'
DATASET_FOLDER = r'BTC-USD'
FILE = r'BTC-USD.csv'
data_loader = YahooFinanceDataLoader(DATASET_FOLDER, FILE, '2018-01-01', load_from_file=True)

# AAPL

# DATASET_NAME = 'AAPL'
# DATASET_FOLDER = r'AAPL'
# FILE = r'AAPL.csv'
# data_loader = YahooFinanceDataLoader(DATASET_FOLDER, FILE, '2018-01-01', load_from_file=True)

# AAL

# DATASET_NAME = 'AAL'
# DATASET_FOLDER = r'AAL'
# FILE = r'AAL.csv'
# data_loader = YahooFinanceDataLoader(DATASET_FOLDER, FILE, '2018-01-01', load_from_file=True)

# # DJI
#
# DATASET_NAME = 'DJI'
# DATASET_FOLDER = r'DJI'
# FILE = r'DJI.csv'
# data_loader = YahooFinanceDataLoader(DATASET_FOLDER, FILE, '2016-01-01', begin_date='2009-01-01', end_date='2018-09-30',
#                                      load_from_file=True)

# S&P

# DATASET_NAME = 'S&P'
# DATASET_FOLDER = 'S&P'
# FILE = 'S&P.csv'
# data_loader = YahooFinanceDataLoader(DATASET_FOLDER, FILE, split_point=2000, end_date='2018-09-25', load_from_file=True)

# GOOGL

# DATASET_NAME = 'GOOGL'
# DATASET_FOLDER = 'GOOGL'
# FILE = 'GOOGL.csv'
# data_loader = YahooFinanceDataLoader(DATASET_FOLDER, FILE, '2018-01-01', load_from_file=True)

# AMD

# DATASET_NAME = 'AMD'
# DATASET_FOLDER = 'AMD'
# FILE = 'AMD.csv'
# data_loader = YahooFinanceDataLoader(DATASET_FOLDER, FILE, split_point=2000, end_date='2018-09-25', load_from_file=True)


#
# data_train = DataForPatternBasedAgent(data_loader.data_train, data_loader.patterns, 'action_deepRL', device, GAMMA,
#                                       n_step, BATCH_SIZE)
# data_test = DataForPatternBasedAgent(data_loader.data_test, data_loader.patterns, 'action_deepRL', device, GAMMA,
#                                      n_step, BATCH_SIZE)
#
data_train = DataAutoPatternExtractionAgent(data_loader.data_train, state_mode,
                                            'action_deepRL', device, GAMMA, n_step,
                                            BATCH_SIZE)
data_test = DataAutoPatternExtractionAgent(data_loader.data_test, state_mode,
                                           'action_deepRL', device, GAMMA, n_step,
                                           BATCH_SIZE)

deepRLAgent = Train(data_train, data_test, DATASET_NAME, BATCH_SIZE=BATCH_SIZE, GAMMA=GAMMA, EPS=EPS,
                    ReplayMemorySize=ReplayMemorySize,
                    TARGET_UPDATE=TARGET_UPDATE,
                    n_actions=n_actions,
                    n_step=n_step)

deepRLAgent.train(10)
file_name = None

deepRLAgent.test(file_name=file_name, action_name=data_train.action_name)
deepRLAgent.test(file_name=file_name, action_name=data_train.action_name, test_type='test')

# ################################ ONLY BUY ######################################

# data_train.data[data_train.action_name] = 'buy'
# ev_agent = Evaluation(data_train.data, data_train.action_name, 1000)
# print('Deep RL Agent')
# ev_agent.evaluate()
#
# data_test.data[data_test.action_name] = 'buy'
# ev_agent = Evaluation(data_test.data, data_train.action_name, 1000)
# print('Deep RL Agent')
# ev_agent.evaluate()
