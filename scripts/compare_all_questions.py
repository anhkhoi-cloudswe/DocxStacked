import json, sqlite3, docx

conn = sqlite3.connect('data/docxstacked.db')
c = conn.cursor()

def check_file(docx_path, exam_id):
    doc = docx.Document(docx_path)
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    
    c.execute('''
        SELECT q."index", a.answer_set, a.vote_breakdown, a.status, q.media_id
        FROM questions q
        JOIN answers a ON q.id = a.question_id
        WHERE q.exam_id = ?
        ORDER BY q.`index`
    ''', (exam_id,))
    rows = c.fetchall()
    
    print('='*85)
    print(f'=== {docx_path} (Exam ID {exam_id}) ===')
    print('='*85)
    diff_list = []
    for q_idx, ans_json, vb_json, status, media_id in rows:
        q_num = q_idx
        vb = json.loads(vb_json) if vb_json else {}
        ai_votes = vb.get('_ai_votes', [])
        ai_parts = [f"{v.get('provider')}:{v.get('answers')}" for v in ai_votes]
        ai_str = ', '.join(ai_parts) if ai_parts else 'None'
        source = vb.get('_source', '')
        
        # docx answer at q_num - 1 (since docx paras are 0-indexed for Q1..Q60)
        docx_ans = paras[q_num - 1] if q_num <= len(paras) else 'N/A'
        
        if source == 'comments':
            # Human votes are present
            comm_votes = {k: v for k, v in vb.items() if not k.startswith('_')}
            human_votes = {}
            for k, v in comm_votes.items():
                w = v
                for ai in ai_votes:
                    if k in ai.get('answers', []):
                        w -= 0.5
                if w > 0:
                    human_votes[k] = w
            
            sorted_human = sorted(human_votes.items(), key=lambda x: (-x[1], x[0]))
            top_score = sorted_human[0][1] if sorted_human else 0
            top_answers = [k for k, sc in sorted_human if sc == top_score]
            top_comm = ', '.join(top_answers)
            
            docx_list = [x.strip() for x in docx_ans.split(',')]
            top_list = [x.strip() for x in top_comm.split(',')]
            
            # If community has a tie (e.g. ['A', 'B']), docx picking either A or B is consistent with community
            if len(top_list) > 1 and len(docx_list) == 1 and docx_list[0] in top_list:
                is_diff = False
            else:
                docx_norm = ', '.join(sorted(docx_list))
                top_norm = ', '.join(sorted(top_list))
                is_diff = (docx_norm != top_norm)
            diff_mark = ' [DIFF]' if is_diff else ''
            
            print(f'Q{q_num:02d}: Docx={docx_ans:<8} | TopComm={top_comm:<8} | AI={ai_str:<24} | Status={status:<10}{diff_mark}')
            if is_diff:
                diff_list.append((q_num, docx_ans, top_comm, ai_str, status))
        else:
            print(f'Q{q_num:02d}: Docx={docx_ans:<8} | TopComm=NO_DATA  | AI={ai_str:<24} | Status={status:<10}')
            
    print('-'*85)
    print(f'Total questions with community votes differing from final docx: {len(diff_list)}')
    if diff_list:
        for d in diff_list:
            print(f'  DIFF: Q{d[0]} Docx={d[1]} TopComm={d[2]} AI={d[3]} Status={d[4]}')
    else:
        print('  LIST IS EMPTY: []')
    print('='*85 + '\n')

check_file('data/output/FUE/MLN122/MLN122 - FUE - FA26 - FE - C1.docx', 1473)
check_file('data/output/FUE/MLN122/MLN122 - FUE - FA26 - FE - C2.docx', 1474)
