"""TASK-019: positive, current Gradebook evidence only; no negative inference."""
import os
TABLE='tblMzgO5ZDvWTtuO'

def scalar(x):
    if isinstance(x,list):return scalar(x[0]) if len(x)==1 else ''
    if isinstance(x,dict):return str(x.get('text') or '')
    return str(x or '').strip()

def counting_items(body):
    items=body.get('grade_item_data')
    if not isinstance(items,dict):raise RuntimeError('task_types_missing_grade_items')
    return {str(n) for n,v in items.items() if str(n).isdigit() and isinstance(v,dict)
            and not v.get('is_grade_column') and not v.get('exclude_from_grade')}

def plan(rows,evidence,semester):
    updates=[];issues=[]
    for r in rows:
        f=r.get('fields',{});rid=r['record_id']
        if scalar(f.get('所属学期'))!=semester:continue
        section=scalar(f.get('SchoologySectionNID'));aid=scalar(f.get('Schoology作业NID'))
        if not section or not aid:
            issues.append({'record_id':rid,'reason':'identity_missing'});continue
        if section not in evidence or aid not in evidence[section]:continue
        current=scalar(f.get('任务类型'))
        if not current:updates.append({'record_id':rid,'fields':{'任务类型':'算分作业'}})
        elif current=='日常作业':issues.append({'record_id':rid,'reason':'manual_type_conflict'})
        elif current=='单独布置':issues.append({'record_id':rid,'reason':'individual_assignment_preserved'})
    return updates,issues

def synchronize(session,request,evidence,apply):
    base=os.environ.get('STUDENT_OPS_BASE_TOKEN','')
    semester=os.environ.get('STUDENT_OPS_SEMESTER_CODE','')
    if not base or not semester:raise RuntimeError('task_types_runtime_missing')
    url=f'https://open.feishu.cn/open-apis/bitable/v1/apps/{base}/tables/{TABLE}/records'
    def read():
        rows=[];page=None;seen=set()
        while True:
            params={'page_size':500}
            if page:params['page_token']=page
            response=request(session,'GET',url,params=params)
            if response.get('code')!=0:raise RuntimeError('task_types_read_failed')
            data=response.get('data',{});rows.extend(data.get('items',[]))
            if not data.get('has_more'):return rows
            page=data.get('page_token')
            if not page or page in seen:raise RuntimeError('task_types_pagination_incomplete')
            seen.add(page)
    updates,issues=plan(read(),evidence,semester)
    result={'planned':len(updates),'updated':0,'exceptions':issues,'dry_run':not apply}
    if apply and updates:
        fresh={r['record_id']:r for r in read()}
        candidates=[]
        for update in updates:
            row=fresh.get(update['record_id'])
            rechecked,_=plan([row] if row else [],evidence,semester)
            if rechecked:candidates.extend(rechecked)
            else:issues.append({'record_id':update['record_id'],'reason':'changed_before_write'})
        for i in range(0,len(candidates),100):
            batch=candidates[i:i+100]
            response=request(session,'POST',url+'/batch_update',json={'records':batch})
            if response.get('code')!=0:raise RuntimeError('task_types_write_failed_no_blind_retry')
            result['updated']+=len(batch)
        saved={r['record_id']:r for r in read()}
        if any(scalar(saved.get(r['record_id'],{}).get('fields',{}).get('任务类型'))!='算分作业' for r in candidates):
            raise RuntimeError('task_types_readback_mismatch')
    return result
