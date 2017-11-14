import sqlite3
import json
import time

from cocoa.web.main.backend import Backend as BaseBackend, get_backend
from cocoa.web.main.backend import DatabaseManager as BaseDatabaseManager
from cocoa.web.main.utils import Status, Messages
from cocoa.web.views.utils import format_message
from cocoa.analysis.utils import reject_transcript

from db_reader import DatabaseReader
from core.event import Event
from analysis.analyze_strategy import StrategyAnalyzer

class DatabaseManager(BaseDatabaseManager):
    @classmethod
    def add_survey_table(cls, cursor):
        cursor.execute(
            '''CREATE TABLE survey (name text, chat_id text, partner_type text, fluent integer,
            honest integer, persuasive integer, fair integer, negotiator integer, coherent integer, comments text)''')

    @classmethod
    def init_database(cls, db_file):
        super(DatabaseManager, cls).init_database(db_file)
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute(
            '''CREATE TABLE bot (chat_id text, type text, config text)'''
        )
        cls.add_survey_table(c)
        conn.commit()
        conn.close()
        return cls(db_file)

    def add_scenarios(self, scenario_db, systems, update=False):
        """Add used scenarios to DB so that we don't collect data on duplicated scenarios.
        """
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()
        for scenario in scenario_db.scenarios_list:
            sid = scenario.uuid
            for agent_type in systems.keys():
                if update:
                    c.execute('''INSERT OR IGNORE INTO scenario VALUES (?,?, "[]", "[]")''', (sid, agent_type))
                else:
                    c.execute('''INSERT INTO scenario VALUES (?,?, "[]", "[]")''', (sid, agent_type))

        conn.commit()
        conn.close()

class Backend(BaseBackend):
    def display_received_event(self, event):
        if event.action == 'offer':
            message = format_message("Your partner made an offer. View it on the right and accept or reject it.", True)
            return {'message': message, 'status': False, 'price': event.data['price']}
        elif event.action == 'accept':
            message = format_message("Congrats, your partner accepted your offer!", True)
            return {'message': message, 'status': False}
        elif event.action == 'reject':
            message = format_message("Sorry, your partner rejected your offer.", True)
            return {'message': message, 'status': False}
        else:
            return super(Backend, self).display_received_event(event)

    def should_reject_chat(self, userid, agent_idx):
        with self.conn:
            controller = self.controller_map[userid]
            cursor = self.conn.cursor()
            chat_id = controller.get_chat_id()
            ex = DatabaseReader.get_chat_example(cursor, chat_id, self.scenario_db).to_dict()
            return reject_transcript(ex, agent_idx, min_tokens=40)

    def get_margin(self, controller, agent_idx):
        with self.conn:
            cursor = self.conn.cursor()
            chat_id = controller.get_chat_id()
            ex = DatabaseReader.get_chat_example(cursor, chat_id, self.scenario_db)
            outcome = controller.get_outcome()
            role = ex.scenario.kbs[agent_idx].facts['personal']['Role']
            if outcome['reward'] == 0:
                return role, None
            else:
                try:
                    price = float(outcome['offer']['price'])
                except (KeyError, ValueError) as e:
                    return role, None
                margin = StrategyAnalyzer.get_margin(ex, price, agent_idx, role, remove_outlier=False)
                return role, margin

    def check_game_over_and_transition(self, cursor, userid, partner_id):
        agent_idx = self.get_agent_idx(userid)
        game_over, game_complete = self.is_game_over(userid)
        controller = self.controller_map[userid]
        chat_id = controller.get_chat_id()

        def verify_chat(userid, agent_idx, is_partner):
            user_name = 'partner' if is_partner else 'user'
            if self.should_reject_chat(userid, agent_idx):
                self.logger.debug("Rejecting chat with ID {:s} for {:s} {:s} (agent ID {:d}), and "
                                  "redirecting".format(chat_id, user_name, userid, agent_idx))
                self.end_chat_and_redirect(cursor, userid,
                                           message=self.messages.Redirect + " " + self.messages.Waiting)
            else:
                msg, _ = self.get_completion_messages(userid)
                self.logger.debug("Accepted chat with ID {:s} for {:s} {:s} (agent ID {:d}), and redirecting to "
                                  "survey".format(chat_id, user_name, userid, agent_idx))
                self.end_chat_and_finish(cursor, userid, message=msg)

        if game_over:
            if not self.is_user_partner_bot(cursor, userid):
                verify_chat(partner_id, 1 - agent_idx, True)
            verify_chat(userid, agent_idx, False)
            return True

        return False

    def get_completion_messages(self, userid):
        """
        Returns two completion messages: one for the current user and one for the user's partner. This function doesn't
        check whether the user's partner is a bot or not. It just decides which user is the winner of the negotiation
        and assigns completion messages accordingly.
        :param userid:
        :return:
        """

        _, game_complete = self.is_game_over(userid)
        if game_complete:
            msg = self.messages.ChatCompleted
            partner_msg = msg
        else:
            msg = self.messages.ChatIncomplete
            partner_msg = msg

        return msg, partner_msg

    def make_offer(self, userid, offer):
        try:
            with self.conn:
                cursor = self.conn.cursor()
                u = self._get_user_info_unchecked(cursor, userid)
                self._update_user(cursor, userid, connected_status=1)
                self.send(userid, Event.OfferEvent(u.agent_index,
                                                   offer,
                                                   str(time.time())))
        except sqlite3.IntegrityError:
            print("WARNING: Rolled back transaction")
            return None

    def accept_offer(self, userid):
        try:
            with self.conn:
                cursor = self.conn.cursor()
                u = self._get_user_info_unchecked(cursor, userid)
                self._update_user(cursor, userid, connected_status=1)
                self.send(userid, Event.AcceptEvent(u.agent_index,
                                                   str(time.time())))
        except sqlite3.IntegrityError:
            print("WARNING: Rolled back transaction")
            return None

    def reject_offer(self, userid):
        try:
            with self.conn:
                cursor = self.conn.cursor()
                u = self._get_user_info_unchecked(cursor, userid)
                self._update_user(cursor, userid, connected_status=1)
                self.send(userid, Event.RejectEvent(u.agent_index,
                                                   str(time.time())))
        except sqlite3.IntegrityError:
            print("WARNING: Rolled back transaction")
            return None

    def quit(self, userid):
        try:
            with self.conn:
                cursor = self.conn.cursor()
                u = self._get_user_info_unchecked(cursor, userid)
                self._update_user(cursor, userid, connected_status=1)
                self.send(userid, Event.QuitEvent(u.agent_index,
                                                  None,
                                                  str(time.time())))
        except sqlite3.IntegrityError:
            print("WARNING: Rolled back transaction")
            return None

    def submit_survey(self, userid, data):
        def _user_finished(userid):
            self._update_user(cursor, userid, status=Status.Finished)

        def _update_scenario_db(chat_id, scenario_id, partner_type):
            # make sure that the # of completed dialogues for the scenario is only updated once if both agents are human
            cursor.execute('''SELECT complete FROM scenario WHERE scenario_id=? AND partner_type=?''',
                           (scenario_id, partner_type))
            complete_set = set(json.loads(cursor.fetchone()[0]))
            complete_set.add(chat_id)
            cursor.execute('''
                UPDATE scenario
                SET complete=?
                WHERE scenario_id=? AND partner_type=?
                AND (SELECT COUNT(survey.name)
                    FROM survey
                    WHERE survey.chat_id=?) = 0;
            ''', (json.dumps(list(complete_set)), scenario_id, partner_type, chat_id))

        try:
            with self.conn:
                cursor = self.conn.cursor()
                user_info = self._get_user_info_unchecked(cursor, userid)
                cursor.execute('''SELECT scenario_id FROM chat WHERE chat_id=?''', (user_info.chat_id,))
                scenario_id = cursor.fetchone()[0]
                _update_scenario_db(user_info.chat_id, scenario_id, user_info.partner_type)
                cursor.execute('INSERT INTO survey VALUES (?,?,?,?,?,?,?,?,?,?)',
                               (userid, user_info.chat_id, user_info.partner_type,
                                data['fluent'], data['honest'], data['persuasive'],
                                data['fair'], data['negotiator'], data['coherent'], data['comments']))
                _user_finished(userid)
                self.logger.debug("User {:s} submitted survey for chat {:s}".format(userid, user_info.chat_id))

                if user_info.partner_type == 'config-rulebased':
                    agent_idx = self.get_agent_idx(userid)
                    bot_agent_idx = 1 - agent_idx
                    controller = self.controller_map[userid]
                    # TODO: get config
                    cursor.execute('''SELECT config FROM bot WHERE chat_id=? AND type=?''', (user_info.chat_id, user_info.partner_type))
                    config = tuple(json.loads(cursor.fetchone()[0]))
                    role, margin = self.get_margin(controller, bot_agent_idx)
                    self.logger.debug("Updating trials for user {}".format(userid))
                    self.logger.debug("scenario_id={}, role={}, margin={}, humanlike={}".format(scenario_id, role, margin, data['negotiator']))
                    self.systems['config-rulebased'].update_trials([
                        (config, user_info.chat_id, {'scenario_id': scenario_id, 'role': role, 'margin': margin, 'humanlike': data['negotiator']}),
                        ])
        except sqlite3.IntegrityError:
            print("WARNING: Rolled back transaction")
