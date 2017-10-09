from collections import defaultdict

from cocoa.core.dataset import Example
from cocoa.analysis.visualizer import Visualizer as BaseVisualizer

from core.scenario import Scenario
from analysis.html_visualizer import HTMLVisualizer

class Visualizer(BaseVisualizer):
    agents = ('human', 'rulebased', 'config-rule')
    agent_labels = {'human': 'Human', 'rulebased': 'Rule-based', 'config-rulebased': 'Config-rulebased'}
    #questions = ('fluent', 'negotiator', 'persuasive', 'fair', 'coherent')
    questions = ('negotiator',)
    question_labels = {"negotiator": 'Humanlikeness'}

    def __init__(self, chats, surveys=None):
        super(Visualizer, self).__init__(chats, surveys)
        mask = None
        self.question_scores = None
        if surveys:
            self.agents, self.question_scores = self.read_eval(self.surveys, mask)

    def filter(self, deprecated):
        print("tried to filter for #bad_worker_ids, this has been deprecated")
        return deprecated

    def html_visualize(self, viewer_mode, html_output, css_file=None, img_path=None, worker_ids=None):
        chats = []
        scenario_to_chats = defaultdict(set)
        dialogue_responses = None
        if self.question_scores:
            dialogue_responses = self.get_dialogue_responses(self.question_scores)

            # Put chats in the order of responses
            chats_with_survey = set()
            for dialogue_id, agent_responses in dialogue_responses.iteritems():
                chat = self.uuid_to_chat[dialogue_id]
                scenario_id = chat['scenario_uuid']
                chats.append((scenario_id, chat))
                chats_with_survey.add(dialogue_id)
                scenario_to_chats[scenario_id].add(dialogue_id)
            chats = [x[1] for x in sorted(chats, key=lambda x: x[0])]
            # Incomplete chats (redirected, no survey)
            for (dialogue_id, chat) in self.uuid_to_chat.iteritems():
                if dialogue_id not in chats_with_survey:
                    chats.append(chat)
        else:
            for (dialogue_id, chat) in self.uuid_to_chat.iteritems():
                scenario_id = chat['scenario_uuid']
                chats.append((scenario_id, chat))
                scenario_to_chats[scenario_id].add(dialogue_id)
            chats = [x[1] for x in sorted(chats, key=lambda x: x[0])]

        html_visualizer = HTMLVisualizer()
        html_visualizer.visualize(viewer_mode, html_output, chats,
            responses=dialogue_responses, css_file=css_file, img_path=img_path)
