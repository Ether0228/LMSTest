import streamlit as st
import requests
import pandas as pd
import os

# --- 1. 配置加载 (优先读取 Streamlit Secrets) ---
def get_config(key):
    # 先找 Streamlit 的 Secrets，再找系统环境变量
    if key in st.secrets:
        return st.secrets[key]
    return os.environ.get(key, "")

APP_ID = get_config("FEISHU_APP_ID")
APP_SECRET = get_config("FEISHU_APP_SECRET")
APP_TOKEN = get_config("FEISHU_APP_TOKEN")
TABLE_ROSTER = get_config("FEISHU_ROSTER_TABLE_ID")
TABLE_MISSING = get_config("FEISHU_MISSING_TABLE_ID")
TABLE_SUBMISSION = get_config("FEISHU_TABLE_ID")

# --- 2. 飞书 API 工具 ---
def get_tenant_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET})
    return resp.json().get("tenant_access_token")

def fetch_feishu_data(table_id, filter_query=""):
    try:
        token = get_tenant_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records"
        headers = {"Authorization": f"Bearer {token}"}
        
        # 修正 1：飞书筛选器建议使用单个 = 号
        # 修正 2：增加 page_size 确保拉取足够数据
        params = {"page_size": 100}
        if filter_query:
            # 将 == 替换为 =
            safe_filter = filter_query.replace("==", "=")
            params["filter"] = safe_filter
        
        response = requests.get(url, headers=headers, params=params)
        
        # 检查 HTTP 状态码
        if response.status_code != 200:
            st.error(f"飞书请求失败，状态码: {response.status_code}")
            st.write(response.text) # 打印出具体的 HTML/错误信息
            return []

        data = response.json()
        
        if data.get("code") != 0:
            st.error(f"飞书接口业务报错: {data.get('msg')}")
            return []
            
        items = data.get("data", {}).get("items", [])
        return [i["fields"] for i in items]
        
    except Exception as e:
        st.error(f"发生意外错误: {e}")
        return []

# --- 3. Streamlit 界面 ---
st.set_page_config(page_title="学生通关指南", page_icon="🎓")

def main():
    st.title("🎓 学生作业通关指南")
    st.markdown("---")

    # 登录逻辑
    if "student_name" not in st.session_state:
        st.subheader("🔑 身份验证")
        auth_mode = st.radio("选择登录方式", ["家长/学生 (Family Code)", "老师测试 (输入姓名)"])
        
        if auth_mode == "家长/学生 (Family Code)":
            code = st.text_input("请输入你的 Family Code:", type="password")
            if st.button("进入系统"):
                # 查花名册
                res = fetch_feishu_data(TABLE_ROSTER, f'CurrentValue.[FamilyCode] == "{code}"')
                if res:
                    st.session_state.student_name = res[0]["学生姓名"]
                    st.rerun()
                else:
                    st.error("无效的代码，请联系老师。")
        else:
            name = st.text_input("请输入学生姓名 (测试用):")
            if st.button("进入系统"):
                st.session_state.student_name = name
                st.rerun()
    
    else:
        # 已登录展示页面
        name = st.session_state.student_name
        st.sidebar.write(f"当前用户: **{name}**")
        if st.sidebar.button("退出登录"):
            del st.session_state.student_name
            st.rerun()

        # 拉取数据
        with st.spinner("正在加载你的通关进度..."):
            missing_data = fetch_feishu_data(TABLE_MISSING, f'CurrentValue.[关联学生] == "{name}"')
            submit_data = fetch_feishu_data(TABLE_SUBMISSION, f'CurrentValue.[学生姓名] == "{name}"')

        # 游戏化组件展示
        col1, col2 = st.columns(2)
        
        # HP计算 (简单逻辑: 100 - 缺交数*10)
        hp = max(0, 100 - len(missing_data) * 10)
        col1.metric("HEALTH (HP)", f"{hp}%")
        col1.progress(hp/100)
        
        # XP计算
        xp = len(submit_data) * 50
        col2.metric("EXPERIENCE (XP)", f"{xp}")
        col2.progress((xp % 500) / 500)

        st.markdown("### 🏹 待补交的任务 (缺交)")
        if missing_data:
            for item in missing_data:
                with st.expander(f"❌ {item.get('缺交概要', '未命名作业')}"):
                    st.write(f"**课程:** {item.get('所属课程', 'N/A')}")
                    st.write(f"**截止日期:** {item.get('最后核验时间', 'N/A')}")
        else:
            st.success("🎉 所有的任务都已完成，目前血量全满！")

        st.markdown("### ✅ 最近完成的挑战")
        if submit_data:
            df = pd.DataFrame(submit_data)[["作业名称", "提交时间"]]
            st.table(df.head(5))

if __name__ == "__main__":
    main()
