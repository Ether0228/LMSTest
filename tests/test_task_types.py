import unittest
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
from unittest.mock import patch
from sync_course_task_types import counting_items,plan,synchronize
def row(kind=None,section='11',aid='22',term='26-S2'):
 return {'record_id':'rec1','fields':{'所属学期':[term],'SchoologySectionNID':section,'Schoology作业NID':aid,'任务类型':kind}}
class Tests(unittest.TestCase):
 def test_blank_positive(self):self.assertEqual(plan([row()],{'11':{'22'}},'26-S2')[0][0]['fields'],{'任务类型':'算分作业'})
 def test_no_grade_not_daily(self):self.assertEqual(plan([row()],{},'26-S2')[0],[])
 def test_old_term(self):self.assertEqual(plan([row(term='26-S1')],{'11':{'22'}},'26-S2')[0],[])
 def test_wrong_section(self):self.assertEqual(plan([row(section='12')],{'11':{'22'}},'26-S2')[0],[])
 def test_conflict(self):self.assertEqual(plan([row(['日常作业'])],{'11':{'22'}},'26-S2')[1][0]['reason'],'manual_type_conflict')
 def test_individual(self):self.assertEqual(plan([row(['单独布置'])],{'11':{'22'}},'26-S2')[0],[])
 def test_idempotent(self):self.assertEqual(plan([row(['算分作业'])],{'11':{'22'}},'26-S2')[0],[])
 def test_no_score_required(self):self.assertEqual(counting_items({'grade_item_data':{'22':{}}}),{'22'})
 def test_exclude(self):self.assertEqual(counting_items({'grade_item_data':{'22':{'exclude_from_grade':True},'23':{'is_grade_column':True}}}),set())
 def test_incomplete(self):
  with self.assertRaises(RuntimeError):counting_items({})
 def test_missing_identity(self):self.assertEqual(plan([row(aid='')],{'11':{'22'}},'26-S2')[0],[])
 def test_pagination_failure(self):
  def req(*a,**kw):return {'code':0,'data':{'items':[],'has_more':True}}
  with patch.dict(os.environ,{'STUDENT_OPS_BASE_TOKEN':'base','STUDENT_OPS_SEMESTER_CODE':'26-S2'}):
   with self.assertRaises(RuntimeError):synchronize(None,req,{},False)
 def test_concurrent_edit_preserved(self):
  reads=iter([[row()],[row(['单独布置'])],[row(['单独布置'])]])
  def req(s,m,u,**kw):
   self.assertEqual(m,'GET');return {'code':0,'data':{'items':next(reads)}}
  with patch.dict(os.environ,{'STUDENT_OPS_BASE_TOKEN':'base','STUDENT_OPS_SEMESTER_CODE':'26-S2'}):
   self.assertEqual(synchronize(None,req,{'11':{'22'}},True)['updated'],0)
 def test_positive_write_and_readback(self):
  saved=row();writes=[]
  def req(s,m,u,**kw):
   if m=='POST':
    writes.append(kw['json']);saved['fields']['任务类型']='算分作业';return {'code':0}
   return {'code':0,'data':{'items':[saved]}}
  with patch.dict(os.environ,{'STUDENT_OPS_BASE_TOKEN':'base','STUDENT_OPS_SEMESTER_CODE':'26-S2'}):
   self.assertEqual(synchronize(None,req,{'11':{'22'}},True)['updated'],1)
  self.assertEqual(writes[0]['records'][0]['fields'],{'任务类型':'算分作业'})
if __name__=='__main__':unittest.main()
