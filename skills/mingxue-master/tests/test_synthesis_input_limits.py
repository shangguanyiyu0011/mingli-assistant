"""User answer budget stays 50 while pair context has one reserved field."""
import os
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]
SKILL=Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT') or (HERE/'package/mingxue-master' if (HERE/'package/mingxue-master').is_dir() else HERE))
sys.path.insert(0,str(SKILL/'scripts'))
import intake_flow
import workflow
from project_store import ProjectError


class AnswerBudgetTests(unittest.TestCase):
    def test_pair_retains_fifty_user_answers_plus_relationship(self):
        person={'person':{'name':'合成预算示例'},'birth':{'date':'2000-08-16','calendar':'solar','timezone':'Asia/Shanghai','time':None}}
        request={'mode':'pair','people':[person,{**person,'person':{'name':'另一合成示例'}}],
                 'preferences':{'systems':['numerology'],'relationship':'collaboration','answers':{str(i):'自述' for i in range(50)}}}
        plan=intake_flow.plan_request(request)
        for item in plan['people']:
            normalized=workflow.normalize_input(item['workflow_input'])
            self.assertEqual(51,len(normalized['questionnaire']))
            self.assertEqual('collaboration',normalized['questionnaire']['_relationship_context'])
        self.assertEqual(50,len(plan['request']['preferences']['answers']))

    def test_more_than_fifty_user_answers_or_reserved_key_are_rejected(self):
        with self.assertRaises(ProjectError):
            workflow.normalize_input({'systems':['numerology'],'questionnaire':{str(i):'x' for i in range(51)}})
        with self.assertRaises(intake_flow.IntakeError):
            intake_flow.normalize_request({'mode':'single','people':[{'person':{'name':'合成'},'birth':{'date':'2000-08-16'}}],
                'preferences':{'answers':{'_relationship_context':'forged'}}})


if __name__=='__main__':unittest.main()
