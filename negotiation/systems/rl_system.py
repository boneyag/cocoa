from cocoa.systems.system import System
from sessions.rl_session import RLSession
from onmt import Optim

class RLSystem(System):
    def __init__(self, system, args):
        self.system = system
        self.optim = self.build_optimizer(args)
        # self.env = env          # should include model attr
        # self.model = env.model  # should include discount attr

    @classmethod
    def name(cls):
        return 'RL-{}'.format(self.system.name())

    def build_optimizer(self, args):
        print('Making optimizer for training.')
        optim = Optim(args.optim, args.learning_rate, args.max_grad_norm,
            model_size=args.rnn_size)
        return optim

    def new_session(self, agent, kb, use_rl=True):
        session = self.system.new_session(agent, kb, use_rl)
        self.optim.set_parameters(session.model.parameters())
        rl_session = RLSession(agent, session, self.optim)
        self.session = rl_session

        return rl_session
