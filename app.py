import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
import os

# ================= 配置 =================
SHEET_NAME = "Schoology_Data"
CREDENTIALS_FILE = "credentials.json"
# =======================================

# --- 1. 数据加载与缓存 ---
@st.cache_data(ttl=60)
def load_and_process_data():
    # 连接 Google Sheets
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sh = client.open(SHEET_NAME)
    
    # 读取原始数据
    df_subs = pd.DataFrame(sh.worksheet("Submissions").get_all_records())
    df_roster_raw = pd.DataFrame(sh.worksheet("Roster").get_all_records())
    df_assign = pd.DataFrame(sh.worksheet("Assignments").get_all_records())
    
    return df_subs, df_roster_raw, df_assign

# --- 2. 核心逻辑处理函数 ---
def process_core_logic(df_subs, df_roster_raw, df_assign):
    # A. 提取 ID
    def get_id(url):
        match = re.search(r'assignment/(\d+)', str(url))
        return match.group(1) if match else None

    df_assign['ID'] = df_assign['Assignment_URL'].apply(get_id)
    
    # 找到 Submissions 里的链接列 (假设包含 http)
    link_col = [c for c in df_subs.columns if df_subs[c].astype(str).str.contains('http').any()]
    if link_col:
        df_subs['ID'] = df_subs[link_col[0]].apply(get_id)
    else:
        df_subs['ID'] = None

    # B. 整理学生选课数据 (宽表变长表)
    # 将 Course_1, Course_2... 合并为一列
    course_cols = [c for c in df_roster_raw.columns if "Course" in c]
    df_roster = df_roster_raw.melt(id_vars=["Student_Name"], value_vars=course_cols, value_name="Course_Name")
    df_roster = df_roster[df_roster["Course_Name"].astype(str).str.strip() != ""] # 去除空值

    # C. 生成“应交作业全集” (Expected)
    # 逻辑：学生选了课 -> 就要交该课的所有作业
    df_expected = pd.merge(df_roster, df_assign, on="Course_Name", how="inner")
    
    # D. 生成“实际提交情况” (Actual)
    # 我们需要判断每一行“应交”是否“已交”
    
    # 为了加速，建立一个提交查询字典
    # 结构: {'作业ID': ['张三提交的原始文本', '李四提交的原始文本']}
    submission_map = {}
    for _, row in df_subs.iterrows():
        aid = row['ID']
        if aid:
            if aid not in submission_map:
                submission_map[aid] = []
            # 假设第2列是内容，或者找包含名字的列
            content_col = df_subs.columns[1] 
            submission_map[aid].append(str(row[content_col]).lower())

    # E. 逐行比对
    results = []
    for _, row in df_expected.iterrows():
        s_name = row['Student_Name']
        a_id = row['ID']
        
        status = "❌ 缺交"
        submit_time = "-"
        
        # 检查是否提交
        if a_id in submission_map:
            # 检查该作业ID下的所有提交文本，是否包含该学生名字
            for sub_text in submission_map[a_id]:
                if s_name.lower() in sub_text:
                    status = "✅ 已交"
                    # 这里可以进一步提取时间，暂时简化
                    submit_time = "已记录" 
                    break
        
        results.append({
            "学生姓名": s_name,
            "课程": row['Course_Name'],
            "作业名称": row['Assignment_Name'],
            "截止日期": row['Due_Date'],
            "状态": status,
            "作业ID": a_id
        })
        
    return pd.DataFrame(results)

# --- 3. 页面主程序 ---
def main():
    st.set_page_config(page_title="作业提交追踪", layout="wide", page_icon="🎓")
    st.title("🎓 Schoology 作业提交追踪系统")

    # 加载数据
    try:
        if st.sidebar.button("🔄 强制刷新数据"):
            st.cache_data.clear()
        
        df_subs, df_roster_raw, df_assign = load_and_process_data()
        
        # 运行核心逻辑
        df_final = process_core_logic(df_subs, df_roster_raw, df_assign)
        
        st.sidebar.success(f"数据已同步 | 提交记录: {len(df_subs)}")
        
    except Exception as e:
        st.error(f"数据加载失败，请检查 Google Sheets 设置: {e}")
        return

    # --- 视图选择 ---
    view_mode = st.radio("请选择视图模式：", ["👤 学生视角 (查个人情况)", "📚 科目/作业视角 (查缺交名单)"], horizontal=True)
    st.divider()

    # === 视图 1：学生视角 ===
    if "学生" in view_mode:
        # 下拉框选择学生
        student_list = df_roster_raw['Student_Name'].unique()
        selected_student = st.selectbox("🔍 请选择学生：", student_list)
        
        if selected_student:
            # 筛选该学生的数据
            student_data = df_final[df_final['学生姓名'] == selected_student]
            
            # 统计指标
            total = len(student_data)
            submitted = len(student_data[student_data['状态'] == "✅ 已交"])
            missing = total - submitted
            
            col1, col2, col3 = st.columns(3)
            col1.metric("应交作业总数", total)
            col2.metric("已完成", submitted)
            col3.metric("缺交", missing, delta_color="inverse")
            
            # 分页展示
            tab1, tab2 = st.tabs(["❌ 缺交列表", "✅ 已交记录"])
            
            with tab1:
                df_missing = student_data[student_data['状态'] == "❌ 缺交"]
                if not df_missing.empty:
                    st.dataframe(df_missing[['课程', '作业名称', '截止日期']], use_container_width=True)
                else:
                    st.success("太棒了！该学生没有缺交作业！")
            
            with tab2:
                df_done = student_data[student_data['状态'] == "✅ 已交"]
                st.dataframe(df_done[['课程', '作业名称', '截止日期']], use_container_width=True)

    # === 视图 2：科目/作业视角 ===
    else:
        # 两级联动筛选
        # 1. 选课程
        course_list = df_assign['Course_Name'].unique()
        selected_course = st.selectbox("1️⃣ 选择课程：", course_list)
        
        # 2. 选该课程下的作业
        if selected_course:
            assign_list_for_course = df_assign[df_assign['Course_Name'] == selected_course]['Assignment_Name'].unique()
            # 增加一个“查看全部”选项
            selected_assign = st.selectbox("2️⃣ 选择作业 (或查看该课程所有缺交)：", ["(查看该课程所有缺交)"] + list(assign_list_for_course))
            
            # 筛选数据
            course_data = df_final[df_final['课程'] == selected_course]
            
            if selected_assign == "(查看该课程所有缺交)":
                # 展示该课程下所有缺交的记录
                missing_all = course_data[course_data['状态'] == "❌ 缺交"]
                st.warning(f"该课程共有 {len(missing_all)} 人次缺交")
                st.dataframe(missing_all[['学生姓名', '作业名称', '截止日期']], use_container_width=True)
            else:
                # 展示特定作业的提交情况
                target_data = course_data[course_data['作业名称'] == selected_assign]
                
                # 饼图统计
                counts = target_data['状态'].value_counts()
                st.bar_chart(counts)
                
                # 缺交名单
                missing_students = target_data[target_data['状态'] == "❌ 缺交"]
                
                if not missing_students.empty:
                    st.error(f"🚨 作业 [{selected_assign}] 缺交名单 ({len(missing_students)}人):")
                    # 把名字显示得大一点
                    for name in missing_students['学生姓名']:
                        st.write(f"- 🔴 **{name}**")
                else:
                    st.balloons()
                    st.success(f"完美！作业 [{selected_assign}] 全班都交齐了！")

if __name__ == "__main__":
    main()