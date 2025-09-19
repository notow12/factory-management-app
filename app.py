import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import pandas as pd
import uuid
from datetime import datetime

#------------------------------------------------------
# 1. 환경 변수 로드
#------------------------------------------------------
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

#------------------------------------------------------
# 2. Supabase 초기화
#------------------------------------------------------
@st.cache_resource
def init_connection():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_connection()

#------------------------------------------------------
# 3. 데이터 조회
#------------------------------------------------------
@st.cache_data(ttl=600)
def get_factories():
    res = supabase.from_('factories').select('*').execute()
    return res.data if res.data else []

@st.cache_data(ttl=600)
def get_equipment(factory_id=None):
    query = supabase.from_('equipment').select('*, factories(name)').order('name')
    if factory_id:
        query = query.eq('factory_id', factory_id)
    res = query.execute()
    return res.data if res.data else []

@st.cache_data(ttl=600)
def get_maintenance_logs(equipment_id=None):
    query = supabase.from_('maintenance_logs').select('*, equipment(name, factories(name))').order('maintenance_date', desc=True)
    if equipment_id:
        query = query.eq('equipment_id', equipment_id)
    res = query.execute()
    return res.data if res.data else []

@st.cache_data(ttl=600)
def get_status_history(equipment_id):
    res = supabase.from_('equipment_status_history').select('*').eq('equipment_id', equipment_id).order('created_at', desc=True).execute()
    return res.data if res.data else []

#------------------------------------------------------
# 4. 데이터 관리 (CRUD)
#------------------------------------------------------
def upload_images(uploaded_files):
    if not uploaded_files:
        return None
    
    image_urls = []
    for uploaded_file in uploaded_files:
        try:
            file_extension = uploaded_file.name.split('.')[-1]
            file_name = f"{uuid.uuid4()}.{file_extension}"
            supabase.storage.from_('equipment_images').upload(file_name, uploaded_file.getvalue(), {'content-type': uploaded_file.type})
            public_url = supabase.storage.from_('equipment_images').get_public_url(file_name)
            image_urls.append(public_url)
        except Exception as e:
            st.error(f"이미지 업로드 실패: {e}")
            return None
    return ",".join(image_urls) if image_urls else None

# 변경: 이미지 URL 업데이트 함수 추가
def update_equipment_images(equipment_id, uploaded_files):
    # 기존 이미지 URL 가져오기
    current_eq_data = supabase.from_('equipment').select('image_url').eq('id', equipment_id).single().execute().data
    old_urls = current_eq_data['image_url'].split(',') if current_eq_data and current_eq_data['image_url'] else []
    
    # 기존 이미지 삭제 (파일 이름만 추출하여)
    for url in old_urls:
        try:
            file_name = url.split('/')[-1]
            supabase.storage.from_('equipment_images').remove([file_name])
        except Exception as e:
            st.warning(f"기존 이미지 삭제 실패: {e}")
    
    # 새 이미지 업로드 및 URL 반환
    return upload_images(uploaded_files)


def add_factory(name, password):
    supabase.from_('factories').insert({'name': name, 'password': password}).execute()
    st.success(f"'{name}' 공장 추가 완료")
    st.cache_data.clear()

def update_factory(factory_id, name, password):
    supabase.from_('factories').update({'name': name, 'password': password}).eq('id', factory_id).execute()
    st.success("공장 정보 업데이트 완료")
    st.cache_data.clear()

def delete_factory(factory_id):
    supabase.from_('factories').delete().eq('id', factory_id).execute()
    st.success("공장 삭제 완료")
    st.cache_data.clear()

def add_equipment(factory_id, name, maker, model, details, image_urls=None):
    supabase.from_('equipment').insert({
        'factory_id': factory_id,
        'name': name,
        'maker': maker,
        'model': model,
        'details': details,
        'image_url': image_urls,
        'status': '정상'
    }).execute()
    st.success(f"'{name}' 설비 추가 완료")
    st.cache_data.clear()

# 변경: 이미지 업데이트 로직 추가
def update_equipment(equipment_id, name, maker, model, details, status, uploaded_images):
    # 이미지 파일이 업로드된 경우에만 이미지 업데이트 함수 호출
    if uploaded_images:
        new_image_urls = update_equipment_images(equipment_id, uploaded_images)
        supabase.from_('equipment').update({
            'name': name,
            'maker': maker,
            'model': model,
            'details': details,
            'status': status,
            'image_url': new_image_urls
        }).eq('id', equipment_id).execute()
    else:
        supabase.from_('equipment').update({
            'name': name,
            'maker': maker,
            'model': model,
            'details': details,
            'status': status
        }).eq('id', equipment_id).execute()
        
    st.success("설비 정보가 업데이트 되었습니다.")
    st.cache_data.clear()

def delete_equipment(equipment_id):
    # 삭제 전에 이미지 파일도 삭제
    current_eq_data = supabase.from_('equipment').select('image_url').eq('id', equipment_id).single().execute().data
    old_urls = current_eq_data['image_url'].split(',') if current_eq_data and current_eq_data['image_url'] else []
    for url in old_urls:
        try:
            file_name = url.split('/')[-1]
            supabase.storage.from_('equipment_images').remove([file_name])
        except Exception as e:
            st.warning(f"이미지 삭제 실패: {e}")

    supabase.from_('equipment').delete().eq('id', equipment_id).execute()
    supabase.from_('maintenance_logs').delete().eq('equipment_id', equipment_id).execute()
    supabase.from_('equipment_status_history').delete().eq('equipment_id', equipment_id).execute()
    st.success("설비 및 관련 데이터 삭제 완료")
    st.cache_data.clear()

def add_log(equipment_id, engineer, action, notes):
    supabase.from_('maintenance_logs').insert({
        'equipment_id': equipment_id,
        'maintenance_date': datetime.now().isoformat(),
        'engineer': engineer,
        'action': action,
        'notes': notes
    }).execute()
    st.success("정비 이력 추가 완료")
    st.cache_data.clear()

def update_log(log_id, engineer, action, notes):
    supabase.from_('maintenance_logs').update({
        'engineer': engineer,
        'action': action,
        'notes': notes
    }).eq('id', log_id).execute()
    st.success("정비 이력 업데이트 완료")
    st.cache_data.clear()

def delete_log(log_id):
    supabase.from_('maintenance_logs').delete().eq('id', log_id).execute()
    st.success("정비 이력 삭제 완료")
    st.cache_data.clear()

def add_status_history(equipment_id, status, notes):
    supabase.from_('equipment_status_history').insert({
        'equipment_id': equipment_id,
        'status': status,
        'notes': notes,
        'created_at': datetime.now().isoformat()
    }).execute()
    supabase.from_('equipment').update({'status': status}).eq('id', equipment_id).execute()
    st.success(f"상태 '{status}' 기록 완료")
    st.cache_data.clear()

#------------------------------------------------------
# 5. Streamlit UI
#------------------------------------------------------
st.set_page_config(page_title="공장 설비 관리 시스템", layout="wide")

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
if 'current_factory' not in st.session_state:
    st.session_state['current_factory'] = None
# 변경: 선택된 설비와 이력 상태를 저장하는 세션 변수 추가
if 'selected_eq_id_admin' not in st.session_state:
    st.session_state['selected_eq_id_admin'] = None
if 'selected_log_id_admin' not in st.session_state:
    st.session_state['selected_log_id_admin'] = None


def set_selected_equipment():
    # 세션 상태에 선택된 설비 ID 저장
    if 'selected_equipment_name_admin_selectbox' in st.session_state:
        equipment_list_admin = get_equipment()
        eq_data = next((eq for eq in equipment_list_admin if eq['name'] == st.session_state.selected_equipment_name_admin_selectbox), None)
        if eq_data:
            st.session_state.selected_eq_id_admin = eq_data['id']
        else:
            st.session_state.selected_eq_id_admin = None

def set_selected_log():
    # 세션 상태에 선택된 이력 ID 저장
    if 'selected_log_id_admin_selectbox' in st.session_state:
        st.session_state.selected_log_id_admin = st.session_state.selected_log_id_admin_selectbox


# 로그인 화면
if not st.session_state['authenticated']:
    st.title("공장 설비 관리 시스템 - 로그인")
    factories_list = get_factories()
    factory_names = [f['name'] for f in factories_list]
    
    with st.form("login_form"):
        selected_factory = st.selectbox("공장 선택", ['공장을 선택하세요'] + factory_names)
        password = st.text_input("비밀번호", type="password")
        
        submitted = st.form_submit_button("로그인", use_container_width=True)
    
    if submitted:
        if selected_factory == '공장을 선택하세요':
            st.error("공장을 선택해 주세요.")
        else:
            factory_data = next((f for f in factories_list if f['name'] == selected_factory), None)
            if factory_data and password == factory_data['password']:
                st.session_state['authenticated'] = True
                st.session_state['current_factory'] = selected_factory
                st.success(f"{selected_factory} 공장 로그인 성공")
                st.rerun()
            else:
                st.error("비밀번호 오류")

else:
    # 로그인 성공 후 메인 화면
    
    # 상단 메뉴
    st.markdown("<style>.menu-btn {margin-right: 10px;}</style>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0;">
            <div style="font-size: 24px; font-weight: bold;">설비 관리 시스템</div>
            <div>현재 공장: {st.session_state['current_factory']}</div>
            <a href="/?logout=true" target="_self">로그아웃</a>
        </div>
        <hr style="border: 1px solid #eee;">
        """, unsafe_allow_html=True
    )
    
    if st.query_params.get("logout"):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()

    tabs = st.tabs(["대시보드", "설비 추가", "정비 이력 추가", "관리자"])
    
    factory = next((f for f in get_factories() if f['name'] == st.session_state['current_factory']), None)
    if factory:
        factory_id = factory['id']
    else:
        st.error("공장 정보 오류")
        st.stop()
    
    # ------------------------ 대시보드 ------------------------
    with tabs[0]:
        st.header("대시보드")
        equipment_list = get_equipment(factory_id)
        if not equipment_list:
            st.info("등록된 설비가 없습니다. '설비 추가' 탭에서 새로운 설비를 추가해 보세요.")
        else:
            for eq in equipment_list:
                status_color = "green" if eq['status'] == '정상' else "red"
                with st.expander(f"[{eq['status']}] {eq['name']} ({eq['maker']}/{eq['model']})", expanded=False):
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        if eq.get('image_url'):
                            image_urls = eq['image_url'].split(',')
                            for url in image_urls:
                                st.image(url.strip(), width='stretch')
                        else:
                            st.warning("이미지 없음")
                        
                        st.subheader("상태 기록")
                        with st.form(f"status_form_{eq['id']}", clear_on_submit=True):
                            new_status = st.radio("상태 변경", ['정상', '고장'], index=0 if eq['status'] == '정상' else 1)
                            notes = st.text_area("변경 사유")
                            if st.form_submit_button("기록"):
                                add_status_history(eq['id'], new_status, notes)
                                st.rerun()

                    with col2:
                        st.subheader("세부 사항")
                        st.markdown(f"**제조사:** {eq['maker']}")
                        st.markdown(f"**모델:** {eq['model']}")
                        st.markdown(f"**세부 내용:** {eq['details']}")
                        st.markdown(f"**현재 상태:** <span style='color:{status_color}; font-weight:bold;'>{eq['status']}</span>", unsafe_allow_html=True)
                        
                        st.subheader("최근 정비 이력 (최대 5개)")
                        logs = get_maintenance_logs(equipment_id=eq['id'])
                        if logs:
                            for log in logs[:5]:
                                st.markdown(f"- **날짜:** {log['maintenance_date'].split('T')[0]}, **엔지니어:** {log['engineer']}, **작업 내용:** {log['action']}, **비고:** {log['notes']}")
                        else:
                            st.info("최근 정비 이력이 없습니다.")

    # ------------------------ 설비 추가 ------------------------
    with tabs[1]:
        st.header("설비 추가")
        with st.form("add_eq_form", clear_on_submit=True):
            name = st.text_input("설비 이름")
            maker = st.text_input("제조사")
            model = st.text_input("모델")
            details = st.text_area("세부 사항")
            uploaded_images = st.file_uploader("설비 이미지 (여러 개 선택 가능)", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            if st.form_submit_button("설비 추가", use_container_width=True):
                image_urls = upload_images(uploaded_images)
                add_equipment(factory_id, name, maker, model, details, image_urls)
                st.rerun()

    # ------------------------ 정비 이력 추가 ------------------------
    with tabs[2]:
        st.header("정비 이력 추가")
        equipment_list = get_equipment(factory_id)
        if not equipment_list:
            st.info("먼저 '설비 추가' 탭에서 설비를 등록해 주세요.")
        else:
            equipment_options = {eq['name']: eq['id'] for eq in equipment_list}
            selected_equipment_name = st.selectbox("정비할 설비 선택", list(equipment_options.keys()))
            
            with st.form("add_log_form", clear_on_submit=True):
                engineer = st.text_input("정비자 이름")
                action = st.text_area("작업 내용")
                notes = st.text_area("비고 (선택 사항)")
                if st.form_submit_button("정비 이력 추가"):
                    if engineer and action:
                        selected_equipment_id = equipment_options[selected_equipment_name]
                        add_log(selected_equipment_id, engineer, action, notes)
                        st.rerun()
                    else:
                        st.error("정비자 이름과 작업 내용을 입력해 주세요.")

    # ------------------------ 관리자 ------------------------
    with tabs[3]:
        st.header("관리자 모드")
        admin_password_input = st.text_input("관리자 비밀번호", type="password")
        
        if admin_password_input == ADMIN_PASSWORD:
            st.success("관리자 인증 성공")
            
            # ------------------------ 설비 관리 ------------------------
            st.subheader("설비 관리")
            equipment_df = pd.DataFrame(get_equipment())
            if not equipment_df.empty:
                equipment_df['factory_name'] = equipment_df['factories'].apply(lambda x: x['name'])
                
                # 변경: 설비 선택 시 초기화되는 버그 수정
                eq_options = ['설비를 선택하세요'] + list(equipment_df['name'])
                st.selectbox(
                    "설비 선택", 
                    eq_options, 
                    key='selected_equipment_name_admin_selectbox',
                    on_change=set_selected_equipment
                )
                
                if st.session_state.selected_eq_id_admin:
                    selected_eq = equipment_df[equipment_df['id'] == st.session_state.selected_eq_id_admin].iloc[0]
                    
                    with st.expander("설비 수정/삭제", expanded=True):
                        with st.form("update_equipment_form"):
                            updated_name = st.text_input("설비명", value=selected_eq['name'])
                            updated_maker = st.text_input("제조사", value=selected_eq['maker'])
                            updated_model = st.text_input("모델명", value=selected_eq['model'])
                            updated_details = st.text_area("세부 사항", value=selected_eq['details'])
                            updated_status = st.selectbox("상태", ['정상', '고장'], index=0 if selected_eq['status'] == '정상' else 1)
                            # 변경: 이미지 수정 기능 추가
                            uploaded_images = st.file_uploader("이미지 수정 (새 이미지 업로드)", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True, key='update_image_uploader')
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button("수정"):
                                    update_equipment(selected_eq['id'], updated_name, updated_maker, updated_model, updated_details, updated_status, uploaded_images)
                                    st.rerun()
                            with col2:
                                if st.form_submit_button("삭제"):
                                    delete_equipment(selected_eq['id'])
                                    st.rerun()
            else:
                st.info("등록된 설비가 없습니다.")

            # ------------------------ 정비 이력 관리 ------------------------
            st.subheader("정비 이력 관리")
            logs_df = pd.DataFrame(get_maintenance_logs())
            if not logs_df.empty:
                logs_df['equipment_name'] = logs_df['equipment'].apply(lambda x: x['name'])
                logs_df['factory_name'] = logs_df['equipment'].apply(lambda x: x['factories']['name'])
                st.dataframe(logs_df[['id', 'equipment_name', 'factory_name', 'maintenance_date', 'engineer', 'action', 'notes']])
                
                # 변경: 이력 선택 시 초기화되는 버그 수정
                st.selectbox(
                    "이력 선택",
                    logs_df['id'],
                    key='selected_log_id_admin_selectbox',
                    on_change=set_selected_log
                )

                if st.session_state.selected_log_id_admin:
                    selected_log = logs_df[logs_df['id'] == st.session_state.selected_log_id_admin].iloc[0]

                    with st.expander("정비 이력 수정/삭제", expanded=True):
                        with st.form("update_log_form"):
                            updated_engineer = st.text_input("정비자", value=selected_log['engineer'])
                            updated_action = st.text_area("작업 내용", value=selected_log['action'])
                            updated_notes = st.text_area("비고", value=selected_log['notes'])
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button("수정"):
                                    update_log(selected_log['id'], updated_engineer, updated_action, updated_notes)
                                    st.rerun()
                            with col2:
                                if st.form_submit_button("삭제"):
                                    delete_log(selected_log['id'])
                                    st.rerun()
            else:
                st.info("등록된 정비 이력이 없습니다.")

            # ------------------------ 공장 관리 ------------------------
            st.subheader("공장 관리")
            factories_df = pd.DataFrame(get_factories())
            st.dataframe(factories_df[['id', 'name', 'password']])
            
            with st.expander("공장 추가/수정/삭제"):
                st.markdown("##### 공장 추가")
                with st.form("add_factory_form", clear_on_submit=True):
                    new_name = st.text_input("새 공장 이름")
                    new_password = st.text_input("새 공장 비밀번호", type="password")
                    if st.form_submit_button("추가"):
                        add_factory(new_name, new_password)
                        st.rerun()
                
                st.markdown("---")
                st.markdown("##### 공장 수정/삭제")
                selected_factory_name = st.selectbox("수정/삭제할 공장 선택", factories_df['name'])
                selected_factory = factories_df[factories_df['name'] == selected_factory_name].iloc[0]
                
                with st.form("update_factory_form"):
                    updated_name = st.text_input("이름", value=selected_factory['name'])
                    updated_password = st.text_input("비밀번호", value=selected_factory['password'], type="password")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.form_submit_button("수정"):
                            update_factory(selected_factory['id'], updated_name, updated_password)
                            st.rerun()
                    with col2:
                        if st.form_submit_button("삭제"):
                            delete_factory(selected_factory['id'])
                            st.rerun()
        elif admin_password_input:
            st.error("관리자 비밀번호가 올바르지 않습니다.")
