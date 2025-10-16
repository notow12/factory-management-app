import streamlit as st
import altair as alt
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import pandas as pd
import uuid
from datetime import datetime, date, time
import json
import re
import requests

# ------------------------------------------------------
# 1. 환경 변수 로드
# ------------------------------------------------------
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# ------------------------------------------------------
# 2. Supabase 초기화
# ------------------------------------------------------
@st.cache_resource
def init_connection():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_connection()

# 필드 정의 (특화 필드만 - 공통 필드는 제외)
FIELD_DEFINITIONS = {
    # 사출기 전용
    'min_mold_thickness': {'label': 'min_mold_thickness', 'type': 'text'},
    'max_mold_thickness': {'label': 'max_mold_thickness', 'type': 'text'},
    'tie_bar_spacing': {'label': 'tie_bar_spacing', 'type': 'text'},
    'plate_thickness': {'label': 'plate_thickness', 'type': 'text'},
    'oil_flow_rate': {'label': 'oil_flow_rate', 'type': 'text'},
    'max_displacement': {'label': 'max_displacement', 'type': 'text'},
    
    # CNC 전용
    'spindle_speed': {'label': '스핀들 속도', 'type': 'text'},
    'table_size': {'label': '테이블 크기', 'type': 'text'},
    'axis_travel': {'label': '축 이동거리', 'type': 'text'},
    'tool_capacity': {'label': '공구 용량', 'type': 'text'},
    
    # 프레스 전용
    'press_capacity': {'label': '프레스 용량', 'type': 'text'},
    'stroke_length': {'label': '스트로크 길이', 'type': 'text'},
    'bed_size': {'label': '베드 크기', 'type': 'text'},
}

# ------------------------------------------------------
# 세션 상태 초기화
# ------------------------------------------------------
if 'accessory_specs' not in st.session_state:
    st.session_state.accessory_specs = []
if 'spare_part_specs' not in st.session_state:
    st.session_state.spare_part_specs = []
if 'documents' not in st.session_state:
    st.session_state.documents = []
if 'add_eq_images' not in st.session_state:
    st.session_state.add_eq_images = []

# 스크류 스펙 초기값 설정 (dict 형식으로 변경)
if 'screw_specs' not in st.session_state:
    st.session_state.screw_specs = {
        'material_spec_description': """A:일반 수지류(PP.PE.ABS.POM.PMMA.PC.PET)
B:GLASS WOOL 포함율 30% 이내(PC-GF,POM-GF,PA-GF,PBT-GF)
C:GLASS WOOL 포함율 30% 이상(난연 ABS, 난연PC,난연 PBI, NYLON6,66)
D:400℃이상 온도 사용 제품""",
        'screw_type_general': '일반 수지용 SCREW',
        'applicable_general': '',
        'screw_type_wear': '내마모성 SCREW',
        'applicable_wear': '',
        'general_cycle': [{'해당 사양': '교체 주기 (월)', 'A': '5', 'B': '5', 'C': '3', 'D': '3'}],
        'wear_resistant_cycle': [{'해당 사양': '교체 주기 (월)', 'A': '10', 'B': '10', 'C': '5', 'D': '5'}]
    }

# 오일 스펙 초기값 설정
if 'oil_specs' not in st.session_state:
    st.session_state.oil_specs = [
        {"구분": "작동유", "적용 작동유 SPCE": "LG 정유", "교체 주기": "9000HR / 1년"},
        {"구분": "SPCE", "적용 작동유 SPCE": "란도 HD 46", "교체 주기": "375 일"}
    ]

# ------------------------------------------------------
# 3. 데이터 조회
# ------------------------------------------------------
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
     query = supabase.from_('maintenance_logs').select('*, equipment(name, factories(name)), action_category').order('maintenance_date', desc=True)
     if equipment_id:
         query = query.eq('equipment_id', equipment_id)
     res = query.execute()
     return res.data if res.data else []

@st.cache_data(ttl=0)

def get_status_history(factory_id=None, equipment_id=None):
    try:
        if equipment_id:
            query = supabase.table('equipment_status_history').select('id, equipment_id, status, notes, created_at')
            query = query.eq('equipment_id', equipment_id)
        elif factory_id:
            # equipment 테이블에서 equipment_id 목록 가져오기
            equipment_list = get_equipment(factory_id)
            equipment_ids = [eq['id'] for eq in equipment_list]
            if not equipment_ids:
                return []
            query = supabase.table('equipment_status_history').select('id, equipment_id, status, notes, created_at')
            query = query.in_('equipment_id', equipment_ids)
        response = query.execute()
        data = response.data
        # equipment 테이블에서 name 매핑
        equipment_map = {eq['id']: eq['name'] for eq in get_equipment(factory_id)}
        for item in data:
            item['equipment'] = {'name': equipment_map.get(item['equipment_id'], 'Unknown')}
        return data
    except Exception as e:
        st.error(f"Error fetching status history: {e}")
        return []

def get_field_definitions():
    """모든 활성화된 필드 정의 조회"""
    try:
        response = supabase.table('field_definitions').select('*').eq('is_active', True).order('field_label').execute()
        return response.data if response.data else []
    except Exception as e:
        st.error(f"필드 정의 조회 실패: {str(e)}")
        return []

def add_field_definition(field_key, field_label, field_type, category):
    """새 필드 정의 추가"""
    try:
        # 중복 체크
        existing = supabase.table('field_definitions').select('id').eq('field_key', field_key).execute()
        if existing.data:
            return False, f"'{field_key}' 필드가 이미 존재합니다."
        
        data = {
            'field_key': field_key,
            'field_label': field_label,
            'field_type': field_type,
            'category': category
        }
        response = supabase.table('field_definitions').insert(data).execute()
        return True, "필드가 추가되었습니다."
    except Exception as e:
        return False, str(e)

def delete_field_definition(field_id):
    """필드 정의 삭제 (soft delete)"""
    try:
        data = {'is_active': False}
        response = supabase.table('field_definitions').update(data).eq('id', field_id).execute()
        return True, "필드가 삭제되었습니다."
    except Exception as e:
        return False, str(e)

# ------------------------------------------------------
# 4. 데이터 관리 (CRUD)
# ------------------------------------------------------
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

def update_equipment_images(equipment_id, uploaded_images):
    current_eq_data = supabase.from_('equipment').select('image_urls').eq('id', equipment_id).single().execute().data
    old_urls = current_eq_data['image_urls'].split(',') if current_eq_data and current_eq_data['image_urls'] else []
    for url in old_urls:
        try:
            file_name = url.split('/')[-1]
            supabase.storage.from_('equipment_images').remove([file_name])
        except Exception as e:
            st.warning(f"기존 이미지 삭제 실패: {e}")
    return upload_images(uploaded_images)

def update_log_images(log_id, uploaded_files):
    current_log_data = supabase.from_('maintenance_logs').select('image_urls').eq('id', log_id).single().execute().data
    old_urls = current_log_data['image_urls'].split(',') if current_log_data and current_log_data['image_urls'] else []
    for url in old_urls:
        try:
            file_name = url.split('/')[-1]
            supabase.storage.from_('equipment_images').remove([file_name])
        except Exception as e:
            st.warning(f"기존 이미지 삭제 실패: {e}")
    return upload_images(uploaded_files)

def add_factory(name, password):
    supabase.from_('factories').insert({'name': name, 'password': password}).execute()
    st.success(f"'{name}' {get_translation('factory_add_success')}")
    st.cache_data.clear()

def update_factory(factory_id, name, password):
    supabase.from_('factories').update({'name': name, 'password': password}).eq('id', factory_id).execute()
    st.success(get_translation('factory_update_success'))
    st.cache_data.clear()
    st.session_state.selected_factory_id_admin = None

def delete_factory(factory_id):
    supabase.from_('factories').delete().eq('id', factory_id).execute()
    st.success(get_translation('factory_delete_success'))
    st.cache_data.clear()
    st.session_state.selected_factory_id_admin = None

def serialize_data_for_json(data):
    if isinstance(data, (datetime, date)):
        return data.isoformat()
    elif isinstance(data, list):
        return [serialize_data_for_json(item) for item in data]
    elif isinstance(data, dict):
        return {key: serialize_data_for_json(value) for key, value in data.items()}
    else:
        return data

def update_equipment(equipment_id, name, product_name, maker, model, details_dict, accessory_specs, spare_part_specs, documents, screw_specs, oil_specs, status, uploaded_images, uploaded_documents=None, oil_notes='', oil_aftercare=''):
    try:
        # 날짜 형식 변환
        for part in spare_part_specs:
            if isinstance(part.get('교체 일자'), date):
                part['교체 일자'] = part['교체 일자'].isoformat()
        for key, value in details_dict.items():
            if isinstance(value, date):
                details_dict[key] = value.isoformat() if value else None
        
        # 스크류 사양 처리
        if not isinstance(screw_specs, dict):
            screw_specs = {}
        else:
            if 'general_cycle_df' in screw_specs and isinstance(screw_specs['general_cycle_df'], pd.DataFrame):
                screw_specs['general_cycle'] = screw_specs['general_cycle_df'].to_dict('records')
                del screw_specs['general_cycle_df']
            if 'wear_resistant_cycle_df' in screw_specs and isinstance(screw_specs['wear_resistant_cycle_df'], pd.DataFrame):
                screw_specs['wear_resistant_cycle'] = screw_specs['wear_resistant_cycle_df'].to_dict('records')
                del screw_specs['wear_resistant_cycle_df']
        
        # equipment 테이블 실제 컬럼 (수정: equipment_grade 추가)
        direct_columns = [
            'product_name', 'maker', 'serial_number', 'production_date',
            'acquisition_cost', 'acquisition_date', 'acquisition_basis',
            'purchase_date', 'installation_location', 'motor_capacity',
            'heater_capacity', 'total_weight', 'other_notes',
            'equipment_grade'  # 추가
        ]
        
        # details_dict를 direct 필드와 extra 필드로 분리
        direct_fields = {}
        extra_fields = {}
        
        for key, value in details_dict.items():
            if key in direct_columns:
                direct_fields[key] = value
            else:
                extra_fields[key] = value
        
        # 작동유 사양에 노트 추가
        oil_specs_with_notes = oil_specs + [{'notes': oil_notes}, {'aftercare': oil_aftercare}]
        
        # 이미지 처리
        if uploaded_images:
            new_image_urls = upload_images(uploaded_images)
            existing_image_urls = supabase.table('equipment').select('image_urls').eq('id', equipment_id).execute().data[0].get('image_urls', '')
            combined_image_urls = f"{existing_image_urls},{new_image_urls}" if existing_image_urls else new_image_urls
        else:
            combined_image_urls = supabase.table('equipment').select('image_urls').eq('id', equipment_id).execute().data[0].get('image_urls', '')
        
        # 문서 처리
        updated_documents = documents.copy() if documents else []
        if uploaded_documents:
            for uploaded_doc in uploaded_documents:
                doc_url = upload_document_to_supabase(uploaded_doc)
                if doc_url:
                    file_data = {
                        '기술 자료명': uploaded_doc.name,
                        '취급 설명서': '',
                        '전기 도면': '',
                        '유.증압도면': '',
                        '윤활 기준표': '',
                        'url': doc_url,
                        'file_type': uploaded_doc.type
                    }
                    if not any(d['기술 자료명'] == file_data['기술 자료명'] for d in updated_documents):  # 이름 기반 중복 체크
                        updated_documents.append(file_data)
        
        # 업데이트 데이터 준비
        update_data = {
            "name": name,
            "model": model,
            "equipment_type": selected_equipment_type,
            "status": status,
            **direct_fields,
            "details": json.dumps(extra_fields, ensure_ascii=False),
            "accessory_specs": json.dumps(accessory_specs, ensure_ascii=False),
            "spare_part_specs": json.dumps(spare_part_specs, ensure_ascii=False),
            "documents": json.dumps(updated_documents, ensure_ascii=False),
            "screw_specs": json.dumps(screw_specs, ensure_ascii=False) if screw_specs else None,
            "oil_specs": json.dumps(oil_specs_with_notes, ensure_ascii=False),
            "image_urls": combined_image_urls
        }
        
        # Supabase 업데이트
        supabase.table('equipment').update(update_data).eq('id', equipment_id).execute()
        st.cache_data.clear()
        # 제출 후 세션 초기화 (중복 방지)
        st.session_state.edit_documents = []  # 세션 초기화
        return True, "설비 정보가 업데이트되었습니다."
    except Exception as e:
        return False, str(e)

def delete_equipment(equipment_id):
    current_eq_data = supabase.from_('equipment').select('image_urls').eq('id', equipment_id).single().execute().data
    old_urls = current_eq_data['image_urls'].split(',') if current_eq_data and current_eq_data['image_urls'] else []
    for url in old_urls:
        try:
            file_name = url.split('/')[-1]
            supabase.storage.from_('equipment_images').remove([file_name])
        except Exception as e:
            st.warning(f"이미지 삭제 실패: {e}")

    supabase.from_('equipment_status_history').delete().eq('equipment_id', equipment_id).execute()
    supabase.from_('maintenance_logs').delete().eq('equipment_id', equipment_id).execute()
    supabase.from_('equipment').delete().eq('id', equipment_id).execute()

    st.success("설비 및 관련 데이터 삭제 완료")
    st.session_state.selected_eq_id_admin = None
    st.cache_data.clear()

def add_log(equipment_id, engineer, action, notes, maintenance_date, maintenance_time, image_urls=None, cost=0.0, action_category=None):
    combined_dt = datetime.combine(maintenance_date, maintenance_time)
    supabase.from_('maintenance_logs').insert({
        'equipment_id': equipment_id,
        'maintenance_date': combined_dt.isoformat(),
        'engineer': engineer,
        'action': action,
        'notes': notes,
        'image_urls': image_urls,
        'cost': cost,
        'action_category': action_category
    }).execute()
    st.success("정비 이력 추가 완료")
    st.cache_data.clear()

def update_log(log_id, engineer, action, notes, uploaded_images, action_category=None):
    if uploaded_images:
        new_image_urls = update_log_images(log_id, uploaded_images)
        supabase.from_('maintenance_logs').update({
            'engineer': engineer,
            'action': action,
            'notes': notes,
            'image_urls': new_image_urls,
            'action_category': action_category
        }).eq('id', log_id).execute()
    else:
        supabase.from_('maintenance_logs').update({
            'engineer': engineer,
            'action': action,
            'notes': notes,
            'action_category': action_category
        }).eq('id', log_id).execute()
    st.success("정비 이력 업데이트 완료")
    st.cache_data.clear()
    st.session_state.selected_log_id_admin = None

def delete_log(log_id):
    current_log_data = supabase.from_('maintenance_logs').select('image_urls').eq('id', log_id).single().execute().data
    old_urls = current_log_data['image_urls'].split(',') if current_log_data and current_log_data['image_urls'] else []
    for url in old_urls:
        try:
            file_name = url.split('/')[-1]
            supabase.storage.from_('equipment_images').remove([file_name])
        except Exception as e:
            st.warning(f"기존 이미지 삭제 실패: {e}")

    supabase.from_('maintenance_logs').delete().eq('id', log_id).execute()
    st.success("정비 이력 삭제 완료")
    st.cache_data.clear()
    st.session_state.selected_log_id_admin = None

def add_status_history(equipment_id, status, notes, history_date, history_time):
    combined_dt = datetime.combine(history_date, history_time)
    supabase.from_('equipment_status_history').insert({
        'equipment_id': equipment_id,
        'status': status,
        'notes': notes,
        'created_at': combined_dt.isoformat()
    }).execute()
    supabase.from_('equipment').update({'status': status}).eq('id', equipment_id).execute()
    st.success(f"상태 '{status}' 기록 완료")
    st.cache_data.clear()

def update_status_history(history_id, status, notes):
    supabase.from_('equipment_status_history').update({
        'status': status,
        'notes': notes
    }).eq('id', history_id).execute()
    st.success("상태 기록이 업데이트 되었습니다.")
    st.cache_data.clear()
    st.session_state.selected_status_id_admin = None

def delete_status_history(history_id):
    supabase.from_('equipment_status_history').delete().eq('id', history_id).execute()
    st.success("상태 기록이 삭제 되었습니다.")
    st.session_state.selected_status_id_admin = None
    st.cache_data.clear()

def get_date_value(date_str):
    if not date_str or date_str.lower() == 'n/a':
        return None
    formats = ['%Y-%m-%d', '%Y/%m/%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    return None

def upload_document_to_supabase(file):
    """Supabase Storage에 문서 업로드"""
    try:
        # 파일명 안전하게 변환 (특수 문자 치환 및 공백 처리)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        original_filename = file.name
        sanitized_filename = re.sub(r'[<>:"/\\|?*\[\]]', '_', original_filename)  # 특수 문자 치환
        sanitized_filename = re.sub(r'\s+', '_', sanitized_filename)  # 공백을 _로 치환
        unique_filename = f"{timestamp}_{uuid.uuid4().hex[:8]}_{sanitized_filename}"  # UUID 추가로 고유성 강화
        
        # "documents" 버킷에 업로드
        response = supabase.storage.from_('documents').upload(unique_filename, file.getvalue(), {
            'content-type': file.type
        })
        # 공개 URL 가져오기
        public_url = supabase.storage.from_('documents').get_public_url(unique_filename)
        return public_url
    except Exception as e:
        st.error(f"파일 업로드 실패: {str(e)}")
        return None

# ============ 설비 템플릿 관리 함수 ============

def get_equipment_templates():
    """모든 활성화된 설비 템플릿 조회"""
    try:
        response = supabase.table('equipment_templates').select('*').eq('is_active', True).order('created_at').execute()
        
        # fields_config가 JSON 문자열이면 파싱 필요
        if response.data:
            for template in response.data:
                if isinstance(template['fields_config'], str):
                    template['fields_config'] = json.loads(template['fields_config'])
        
        return response.data if response.data else []
    except Exception as e:
        st.error(f"템플릿 조회 실패: {str(e)}")
        return []

def get_template_by_name(name):
    """특정 이름의 템플릿 조회"""
    try:
        response = supabase.table('equipment_templates').select('*').eq('name', name).eq('is_active', True).single().execute()  # is_active 체크 추가
        return response.data
    except Exception as e:
        return None

def add_equipment_template(name, display_name, fields_config):
    """새 설비 템플릿 추가"""
    try:
        # 중복 체크 추가
        existing = supabase.table('equipment_templates').select('id').eq('name', name).execute()
        if existing.data:
            return False, f"'{name}' 템플릿이 이미 존재합니다."
        
        data = {
            'name': name,
            'display_name': display_name,
            'fields_config': fields_config
        }
        response = supabase.table('equipment_templates').insert(data).execute()
        return True, "템플릿이 추가되었습니다."
    except Exception as e:
        return False, str(e)

def update_equipment_template(template_id, name, display_name, fields_config):
    """설비 템플릿 수정"""
    try:
        # 현재 이름 가져오기
        current = supabase.table('equipment_templates').select('name').eq('id', template_id).single().execute().data
        if not current:
            return False, "템플릿을 찾을 수 없습니다."
        
        current_name = current['name']
        
        # 이름 변경 시 중복 체크
        if name != current_name:
            existing = supabase.table('equipment_templates').select('id').eq('name', name).execute()
            if existing.data:
                return False, f"'{name}' 템플릿이 이미 존재합니다."
        
        data = {
            'name': name,
            'display_name': display_name,
            'fields_config': fields_config,
            'updated_at': datetime.now().isoformat()
        }
        response = supabase.table('equipment_templates').update(data).eq('id', template_id).execute()
        return True, "템플릿이 수정되었습니다."
    except Exception as e:
        return False, str(e)

# UI 함수
def render_delete_ui(template_id):
    st.warning(f"템플릿(ID={template_id})을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ 삭제하기", key=f"delete_{template_id}"):
            success, message = delete_equipment_template(template_id)
            if success:
                st.success(message)
            else:
                st.error(message)

    with col2:
        if st.button("❌ 취소", key=f"cancel_{template_id}"):
            st.info("삭제가 취소되었습니다.")

# 필드 정의 (모든 가능한 필드)
@st.cache_data(ttl=300)  # 5분 캐시
def load_field_definitions():
    """DB에서 필드 정의를 로드하여 딕셔너리로 반환"""
    fields = get_field_definitions()
    field_dict = {}
    for field in fields:
        if field['category'] == 'specific':
            field_dict[field['field_key']] = {
                'label': field['field_label'],
                'type': field['field_type']
            }
    return field_dict

# ------------------------------------------------------
# 5. 다국어 지원 딕셔너리
# ------------------------------------------------------
TRANSLATIONS = {
    'ko': {
        'title': '공장 설비 관리 시스템',
        'login_title': '로그인',
        'select_factory': '공장 선택',
        "equipment_age": "설비 연식",
        "years": "년 경과",
        'enter_password': '비밀번호',
        'login_button': '로그인',
        'login_success': '로그인 성공',
        'specific_fields': '전용 사양',
        'login_fail': '비밀번호 오류',
        'current_factory': '현재 공장',
        'action_category': '정비 이력 세부 분류',
        'electrical': '전장',
        'mechanical': '기구부',
        'drive': '구동부',
        'other_category': '기타',
        'custom_sections': '커스텀 섹션',
        'no_specific_fields': '전용 사양 정보가 없습니다.',
        'logout': '로그아웃',
        'dashboard': '대시보드',
        'add_equipment': '설비 추가',
        'add_maintenance_log': '정비 이력 추가',
        'view_maintenance_log': '정비 이력 확인',
        'add_row_instruction': '테이블에서 '+' 버튼을 눌러 행을 추가하세요.',
        'record_status': '상태 기록',
        'admin_mode': '관리자',
        'no_equipment_registered': '등록된 설비가 없습니다. 새로운 설비를 추가해 보세요.',
        'status': '상태',
        'normal': '정상',
        'faulty': '고장',
        'sold': '매각',
        'change_status': '상태 변경',
        'notes': '비고',
        'record_button': '기록',
        'recent_maintenance_logs': '최근 정비 이력 (최대 5개)',
        'no_recent_logs': '최근 정비 이력이 없습니다.',
        'equipment_name': '설비 이름',
        'maker': '제조사',
        'model': '모델',
        'details': '세부 사항',
        'upload_image': '설비 이미지 (여러 개 선택 가능)',
        'add_equipment_button': '설비 추가',
        'add_success': '설비 추가 완료',
        'select_equipment': '정비할 설비 선택',
        'engineer_name': '엔지니어 이름',
        'maintenance_action': '정비 작업 내용',
        'maintenance_date': '정비 날짜',
        'maintenance_time': '정비 시간',
        'add_log_button': '이력 추가',
        'no_logs': '선택한 설비의 정비 이력이 없습니다.',
        'view_detail_log': '상세 이력을 볼 항목 선택',
        'attachments': '첨부 이미지',
        'no_attachments': '첨부된 이미지가 없습니다.',
        'recent_status_history': '최근 상태 기록',
        'no_status_history': '기록된 상태 이력이 없습니다.',
        'admin_password': '관리자 비밀번호를 입력하세요',
        'admin_login_success': '관리자 모드 로그인 성공',
        'admin_login_fail': '관리자 비밀번호가 올바르지 않습니다.',
        'update_delete_equipment': '설비 수정/삭제',
        'select_equipment_admin': '수정/삭제할 설비 선택',
        'update_button': '수정',
        'delete_button': '삭제',
        'update_log_admin': '정비 이력 수정/삭제',
        'select_log_admin': '수정/삭제할 정비 이력 선택',
        'update_status_admin': '상태 기록 수정/삭제',
        'select_status_admin': '수정/삭제할 상태 기록 선택',
        'add_factory': '공장 추가',
        'factory_name': '공장 이름',
        'password': '비밀번호',
        'add_factory_button': '추가',
        'factory_update_delete': '공장 수정/삭제',
        'select_factory_admin': '수정/삭제할 공장 선택',
        'update_success': '설비 정보가 업데이트 되었습니다.',
        'log_update_success': '정비 이력 업데이트 완료',
        'log_delete_success': '정비 이력 삭제 완료',
        'status_update_success': '상태 기록이 업데이트 되었습니다.',
        'status_delete_success': '상태 기록이 삭제 되었습니다.',
        'factory_add_success': ' 공장 추가 완료',
        'factory_update_success': '공장 정보 업데이트 완료',
        'factory_delete_success': '공장 삭제 완료',
        'basic_info': '기본 정보',
        'equipment_details': '설비 상세 정보',
        'capacity_specs': '용량 및 규격 명세서',
        'add_accessory_row': '부속기기 행 추가',
        'accessory_specs': '부속기기 명세서',
        'add_spare_part_row': 'SPARE PART 행 추가',
        'spare_part_specs': 'SPARE PART 부품 교체 주기',
        'add_document_row': '기타 문서 행 추가',
        'documents': '기타 문서',
        'screw_specs': '스크류 교체 주기 및 표준',
        'screw_material_specs': '스크류 재료 사양',
        'screw_table_general': '일반용 SCREW',
        'screw_table_wear': '내마모성 SCREW',
        'oil_specs': '작동유 교체 주기 및 표준',
        'oil_table_standard': '교체 주기 및 표준',
        'oil_notes': '1년 경과 후 사후 관리 방안',
        'other_notes': '기타사항',
        'purchase_company': '구입처',
        'spec': 'SPEC',
        'amount': '주유량',
        'viscosity_date': '점도 일자',
        'viscosity_result': '측정 결과',
        'log_details': '상세 정비 이력',
        'col_seq': '순번',
        'col_accessory_name': '부속기기 명',
        'col_accessory_type': '형식',
        'col_accessory_serial': '제작번호',
        'col_capacity_spec': '용량 및 규격',
        'col_maker': '제조처',
        'col_notes': '비고',
        'col_spare_part': 'SPARE PART',
        'col_maintenance_cycle': '교체 주기',
        'col_replacement_date': '교체 일자',
        'col_doc_name': '기술 자료명',
        'col_manual': '취급 설명서',
        'col_electric_drawing': '전기 도면',
        'col_hydraulic_drawing': '유.증압도면',
        'col_lubrication_std': '윤활 기준표',
        'col_relevant_item': '해당사항',
        'col_category': '구분',
        'col_applicable_oil': '적용 작동유 SPCE',
        'col_log_id': '이력 ID',
        'col_history_id': '기록 ID',
        'col_created_at': '생성일',
        'col_equipment_name': '설비명',
        'col_status': '상태',
        'col_engineer': '엔지니어',
        'col_action': '작업 내용',
        'no_custom_sections': '커스텀 섹션 설정이 없습니다.',
        'no_active_custom_sections': '활성화된 커스텀 섹션이 없습니다.',
        'col_image_urls': '첨부 이미지 URL',
        "product_name": "제품 이름",
        "serial_number": "일련번호",
        "production_date": "제조일",
        "acquisition_cost": "취득 원가",
        "acquisition_date": "취득일",
        "acquisition_basis": "취득 근거",
        "purchase_date": "구입일",
        "installation_location": "설치 위치",
        "equipment_grade": "설비 등급",
        "min_mold_thickness": "최소 금형 두께",
        "max_mold_thickness": "최대 금형 두께",
        "tie_bar_spacing": "타이바 간격",
        "plate_thickness": "형판 두께",
        "oil_flow_rate": "기계 유량",
        "max_displacement": "최대 계량량",
        'motor_capacity_specs': 'MOTOR 용량',
        'heater_capacity_specs': '히터 용량',
        'total_weight': '기계 총 중량(ton)',
        'error_loading_data': '데이터 로딩 오류',
        'status_updated': '상태가 업데이트되었습니다.',
        'general_screw': '일반용 SCREW',
        'wear_resistant_screw': '내마모성 SCREW',
        'material_spec_description': '재료 사양',
        'no_active_sections': '활성화된 섹션이 없습니다.'
    },
    'vi': {
        'title': 'Hệ thống Quản lý Thiết bị Nhà máy',
        'login_title': 'Đăng nhập',
        'select_factory': 'Chọn nhà máy',
        "equipment_age": "Tuổi thiết bị",
        "years": "năm đã qua",
        'enter_password': 'Mật khẩu',
        'login_button': 'Đăng nhập',
        'login_success': 'Đăng nhập thành công',
        'login_fail': 'Mật khẩu sai',
        'current_factory': 'Nhà máy hiện tại',
        'logout': 'Đăng xuất',
        'dashboard': 'Trang chủ',
        'add_equipment': 'Thêm thiết bị',
        'add_maintenance_log': 'Thêm lịch sử bảo trì',
        'action_category': 'Phân loại chi tiết lịch sử bảo trì',
        'electrical': 'Điện',
        'mechanical': 'Cơ khí',
        'drive': 'Truyền động',
        'other_category': 'Khác',
        'view_maintenance_log': 'Xem lịch sử bảo trì',
        'custom_sections': 'Phần tùy chỉnh',
        'specific_fields': 'Thông số chuyên dụng',
        'record_status': 'Ghi lại trạng thái',
        'admin_mode': 'Quản trị viên',
        'no_equipment_registered': 'Chưa có thiết bị nào được đăng ký. Hãy thử thêm một thiết bị mới.',
        'no_custom_sections': 'Không có cài đặt phần tùy chỉnh.',
        'no_active_custom_sections': 'Không có phần tùy chỉnh được kích hoạt.',
        'status': 'Trạng thái',
        'normal': 'Bình thường',
        'faulty': 'Hỏng',
        'sold': 'bán',
        'no_specific_fields': 'Không có thông tin thông số chuyên dụng.',
        'change_status': 'Thay đổi trạng thái',
        'notes': 'Ghi chú',
        'record_button': 'Ghi lại',
        'recent_maintenance_logs': 'Lịch sử bảo trì gần đây (tối đa 5)',
        'add_row_instruction': 'Nhấn nút '+' trong bảng để thêm hàng.',
        'no_recent_logs': 'Không có lịch sử bảo trì gần đây.',
        'equipment_name': 'Tên thiết bị',
        'maker': 'Nhà sản xuất',
        'model': 'Mẫu mã',
        'details': 'Chi tiết',
        'upload_image': 'Hình ảnh thiết bị (có thể chọn nhiều)',
        'add_equipment_button': 'Thêm thiết bị',
        'add_success': 'Đã thêm thiết bị thành công',
        'select_equipment': 'Chọn thiết bị để bảo trì',
        'engineer_name': 'Tên kỹ sư',
        'maintenance_action': 'Nội dung công việc bảo trì',
        'maintenance_date': 'Ngày bảo trì',
        'maintenance_time': 'Thời gian bảo trì',
        'add_log_button': 'Thêm lịch sử',
        'no_logs': 'Không có lịch sử bảo trì cho thiết bị đã chọn.',
        'view_detail_log': 'Chọn mục để xem chi tiết',
        'attachments': 'Tệp đính kèm',
        'no_attachments': 'Không có hình ảnh đính kèm.',
        'recent_status_history': 'Lịch sử trạng thái gần đây',
        'no_status_history': 'Không có lịch sử trạng thái được ghi lại.',
        'admin_password': 'Nhập mật khẩu quản trị viên',
        'admin_login_success': 'Đăng nhập quản trị viên thành công',
        'admin_login_fail': 'Mật khẩu quản trị viên không chính xác.',
        'update_delete_equipment': 'Cập nhật/Xóa thiết bị',
        'select_equipment_admin': 'Chọn thiết bị để cập nhật/xóa',
        'update_button': 'Cập nhật',
        'delete_button': 'Xóa',
        'update_log_admin': 'Cập nhật/Xóa lịch sử bảo trì',
        'select_log_admin': 'Chọn lịch sử bảo trì để cập nhật/xóa',
        'update_status_admin': 'Cập nhật/Xóa lịch sử trạng thái',
        'select_status_admin': 'Chọn lịch sử trạng thái để cập nhật/xóa',
        'add_factory': 'Thêm nhà máy',
        'factory_name': 'Tên nhà máy',
        'password': 'Mật khẩu',
        'add_factory_button': 'Thêm',
        'factory_update_delete': 'Cập nhật/Xóa nhà máy',
        'select_factory_admin': 'Chọn nhà máy để cập nhật/xóa',
        'update_success': 'Thông tin thiết bị đã được cập nhật.',
        'log_update_success': 'Đã cập nhật lịch sử bảo trì thành công',
        'log_delete_success': 'Đã xóa lịch sử bảo trì thành công',
        'status_update_success': 'Đã cập nhật lịch sử trạng thái thành công.',
        'status_delete_success': 'Đã xóa lịch sử trạng thái thành công.',
        'factory_add_success': 'Đã thêm nhà máy thành công',
        'factory_update_success': 'Đã cập nhật thông tin nhà máy thành công',
        'factory_delete_success': 'Đã xóa nhà máy thành công',
        'basic_info': 'Thông tin cơ bản',
        'equipment_details': 'Chi tiết thiết bị',
        'capacity_specs': 'Dung tích và thông số kỹ thuật',
        'add_accessory_row': 'Thêm dòng phụ kiện',
        'accessory_specs': 'Thông số kỹ thuật phụ kiện',
        'add_spare_part_row': 'Thêm dòng phụ tùng thay thế',
        'spare_part_specs': 'Chu kỳ thay thế phụ tùng',
        'add_document_row': 'Thêm dòng tài liệu khác',
        'documents': 'Tài liệu khác',
        'screw_specs': 'Chu kỳ thay thế và tiêu chuẩn vít',
        'screw_material_specs': 'Thông số kỹ thuật vật liệu vít',
        'screw_table_general': 'Vít thông thường',
        'screw_table_wear': 'Vít chống mài mòn',
        'oil_specs': 'Chu kỳ thay thế và tiêu chuẩn dầu thủy lực',
        'oil_table_standard': 'Tiêu chuẩn và chu kỳ thay thế',
        'oil_notes': 'Kế hoạch bảo trì sau 1 năm',
        'other_notes': 'Các ghi chú khác',
        'purchase_company': 'Công ty mua hàng',
        'spec': 'SPEC',
        'amount': 'Số lượng dầu đã đổ',
        'viscosity_date': 'Ngày đo độ nhớt',
        'viscosity_result': 'Kết quả đo',
        'log_details': 'Chi tiết lịch sử bảo trì',
        'col_seq': 'STT',
        'col_accessory_name': 'Tên phụ kiện',
        'col_accessory_type': 'Loại',
        'col_accessory_serial': 'Sê-ri',
        'col_capacity_spec': 'Dung tích và TS kỹ thuật',
        'col_maker': 'Nhà sản xuất',
        'col_notes': 'Ghi chú',
        'col_spare_part': 'PHỤ TÙNG',
        'col_maintenance_cycle': 'Chu kỳ bảo trì',
        'col_replacement_date': 'Ngày thay thế',
        'col_doc_name': 'Tên tài liệu kỹ thuật',
        'col_manual': 'Sách hướng dẫn sử dụng',
        'col_electric_drawing': 'Bản vẽ điện',
        'col_hydraulic_drawing': 'Bản vẽ thủy lực',
        'col_lubrication_std': 'Bảng tiêu chuẩn bôi trơn',
        'col_relevant_item': 'Mục liên quan',
        'col_category': 'Phân loại',
        'col_applicable_oil': 'TS kỹ thuật dầu áp dụng',
        'col_log_id': 'ID Lịch sử',
        'col_history_id': 'ID Ghi lại',
        'col_created_at': 'Ngày tạo',
        'col_equipment_name': 'Tên TB',
        'col_status': 'Trạng thái',
        'col_engineer': 'Kỹ sư',
        'col_action': 'Nội dung công việc',
        'col_image_urls': 'URL hình ảnh đính kèm',
        'product_name': 'Tên sản phẩm',
        'serial_number': 'Số seri',
        'production_date': 'Ngày sản xuất',
        'acquisition_cost': 'Giá mua lại',
        'acquisition_date': 'Ngày mua lại',
        'acquisition_basis': 'Cơ sở mua lại',
        'purchase_date': 'Ngày mua',
        'installation_location': 'Vị trí lắp đặt',
        "equipment_grade": "Cấp độ thiết bị",
        'min_mold_thickness': 'Độ dày khuôn tối thiểu',
        'max_mold_thickness': 'Độ dày khuôn tối đa',
        'tie_bar_spacing': 'Khoảng cách thanh giằng',
        'plate_thickness': 'Độ dày tấm',
        'oil_flow_rate': 'Tốc độ dòng dầu',
        'max_displacement': 'Độ dịch chuyển tối đa',
        'no_active_sections': 'Không có phần nào được kích hoạt.',
        'total_weight': "Tổng trọng lượng"
    },
    'th': {
        'title': 'ระบบจัดการอุปกรณ์โรงงาน',
        'login_title': 'เข้าสู่ระบบ',
        'select_factory': 'เลือกโรงงาน',
        "equipment_age": "อายุของอุปกรณ์",
        "years": "ปีที่ผ่านมา",
        'enter_password': 'รหัสผ่าน',
        'login_button': 'เข้าสู่ระบบ',
        'login_success': 'เข้าสู่ระบบสำเร็จ',
        'login_fail': 'รหัสผ่านผิด',
        'current_factory': 'โรงงานปัจจุบัน',
        'logout': 'ออกจากระบบ',
        'dashboard': 'แดชบอร์ด',
        'add_equipment': 'เพิ่มอุปกรณ์',
        'add_maintenance_log': 'เพิ่มประวัติการบำรุงรักษา',
        'view_maintenance_log': 'ดูประวัติการบำรุงรักษา',
        'record_status': 'บันทึกสถานะ',
        'specific_fields': 'ข้อกำหนดเฉพาะ',
        'admin_mode': 'ผู้ดูแลระบบ',
        'no_equipment_registered': 'ยังไม่มีอุปกรณ์ที่ลงทะเบียน โปรดลองเพิ่มอุปกรณ์ใหม่',
        'capacity_specs': 'ปริมาณและข้อมูลจำเพาะ',
        'motor_capacity_specs': 'ความจุ MOTOR',
        'heater_capacity_specs': 'ความจุของฮีตเตอร์',
        'total_weight': 'น้ำหนักรวมเครื่องจักร (ตัน)',
        'add_row_instruction': 'กดปุ่ม '+' ในตารางเพื่อเพิ่มแถว',
        'status': 'สถานะ',
        'no_specific_fields': 'ไม่มีข้อมูลข้อกำหนดเฉพาะ.',
        'normal': 'ปกติ',
        'faulty': 'ชำรุด',
        'sold': 'ขาย',
        'change_status': 'เปลี่ยนสถานะ',
        'notes': 'หมายเหตุ',
        'custom_sections': 'ส่วนที่กำหนดเอง',
        'no_custom_sections': 'ไม่มีส่วนที่กำหนดเอง.',
        'no_active_custom_sections': 'ไม่มีส่วนที่กำหนดเองที่เปิดใช้งาน.',
        'record_button': 'บันทึก',
        'recent_maintenance_logs': 'ประวัติการบำรุงรักษาล่าสุด (สูงสุด 5 รายการ)',
        'no_recent_logs': 'ไม่มีประวัติการบำรุงรักษาล่าสุด',
        'equipment_name': 'ชื่ออุปกรณ์',
        'maker': 'ผู้ผลิต',
        'model': 'รุ่น',
        'details': 'รายละเอียด',
        'upload_image': 'รูปภาพอุปกรณ์ (สามารถเลือกได้หลายไฟล์)',
        'action_category': 'หมวดหมู่ประวัติการบำรุงรักษา',
        'electrical': 'ไฟฟ้า',
        'mechanical': 'กลไก',
        'drive': 'ระบบขับเคลื่อน',
        'other_category': 'อื่นๆ',
        'add_equipment_button': 'เพิ่มอุปกรณ์',
        'add_success': 'เพิ่มอุปกรณ์สำเร็จ',
        'select_equipment': 'เลือกอุปกรณ์สำหรับการบำรุงรักษา',
        'engineer_name': 'ชื่อวิศวกร',
        'maintenance_action': 'รายละเอียดการบำรุงรักษา',
        'maintenance_date': 'วันที่บำรุงรักษา',
        'maintenance_time': 'เวลาบำรุงรักษา',
        'add_log_button': 'เพิ่มประวัติ',
        'no_logs': 'ไม่มีประวัติการบำรุงรักษาสำหรับอุปกรณ์ที่เลือก',
        'view_detail_log': 'เลือกรายการเพื่อดูรายละเอียด',
        'attachments': 'รูปภาพที่แนบ',
        'no_attachments': 'ไม่มีรูปภาพแนบ',
        'recent_status_history': 'ประวัติสถานะล่าสุด',
        'no_status_history': 'ไม่มีประวัติสถานะที่บันทึกไว้',
        'admin_password': 'ป้อนรหัสผ่านผู้ดูแลระบบ',
        'admin_login_success': 'เข้าสู่ระบบผู้ดูแลระบบสำเร็จ',
        'admin_login_fail': 'รหัสผ่านผู้ดูแลระบบไม่ถูกต้อง',
        'update_delete_equipment': 'แก้ไข/ลบอุปกรณ์',
        'select_equipment_admin': 'เลือกอุปกรณ์ที่จะแก้ไข/ลบ',
        'update_button': 'แก้ไข',
        'delete_button': 'ลบ',
        'update_log_admin': 'แก้ไข/ลบประวัติการบำรุงรักษา',
        'select_log_admin': 'เลือกประวัติการบำรุงรักษาที่จะแก้ไข/ลบ',
        'update_status_admin': 'แก้ไข/ลบประวัติสถานะ',
        'select_status_admin': 'เลือกประวัติสถานะที่จะแก้ไข/ลบ',
        'add_factory': 'เพิ่มโรงงาน',
        'factory_name': 'ชื่อโรงงาน',
        'password': 'รหัสผ่าน',
        'add_factory_button': 'เพิ่ม',
        'factory_update_delete': 'แก้ไข/ลบโรงงาน',
        'select_factory_admin': 'เลือกโรงงานที่จะแก้ไข/ลบ',
        'update_success': 'อัปเดตข้อมูลอุปกรณ์แล้ว',
        'log_update_success': 'อัปเดตประวัติการบำรุงรักษาสำเร็จ',
        'log_delete_success': 'ลบประวัติการบำรุงรักษาสำเร็จ',
        'status_update_success': 'อัปเดตประวัติสถานะแล้ว',
        'status_delete_success': 'ลบประวัติสถานะแล้ว',
        'factory_add_success': 'เพิ่มโรงงานสำเร็จ',
        'factory_update_success': 'อัปเดตข้อมูลโรงงานสำเร็จ',
        'factory_delete_success': 'ลบโรงงานสำเร็จ',
        'basic_info': 'ข้อมูลพื้นฐาน',
        'equipment_details': 'รายละเอียดอุปกรณ์',
        'capacity_specs': 'ปริมาณและข้อมูลจำเพาะ',
        'add_accessory_row': 'เพิ่มแถวอุปกรณ์เสริม',
        'accessory_specs': 'ข้อมูลจำเพาะอุปกรณ์เสริม',
        'add_spare_part_row': 'เพิ่มแถวอะไหล่',
        'spare_part_specs': 'รอบการเปลี่ยนอะไหล่',
        'add_document_row': 'เพิ่มแถวเอกสารอื่น ๆ',
        'documents': 'เอกสารอื่น ๆ',
        'screw_specs': 'รอบการเปลี่ยนและมาตรฐานสกรู',
        'screw_material_specs': 'ข้อมูลจำเพาะวัสดุสกรู',
        'screw_table_general': 'สกรูทั่วไป',
        'screw_table_wear': 'สกรูทนการสึกหรอ',
        'oil_specs': 'รอบการเปลี่ยนและมาตรฐานน้ำมันไฮดรอลิก',
        'oil_table_standard': 'มาตรฐานและรอบการเปลี่ยน',
        'oil_notes': 'แผนการบำรุงรักษาหลัง 1 ปี',
        'other_notes': 'บันทึกอื่นๆ',
        'purchase_company': 'บริษัทที่ซื้อ',
        'spec': 'SPEC',
        'amount': 'ปริมาณน้ำมันที่เติม',
        'viscosity_date': 'วันที่วัดความหนืด',
        'viscosity_result': 'ผลการวัด',
        'log_details': 'รายละเอียดประวัติการบำรุงรักษา',
        'col_seq': 'ลำดับ',
        'col_accessory_name': 'ชื่ออุปกรณ์เสริม',
        'col_accessory_type': 'รูปแบบ',
        'col_accessory_serial': 'หมายเลขการผลิต',
        'col_capacity_spec': 'ปริมาณและข้อมูลจำเพาะ',
        'col_maker': 'ผู้ผลิต',
        'col_notes': 'หมายเหตุ',
        'col_spare_part': 'อะไหล่',
        'col_maintenance_cycle': 'รอบการบำรุงรักษา',
        'col_replacement_date': 'วันที่เปลี่ยน',
        'col_doc_name': 'ชื่อข้อมูลทางเทคนิค',
        'col_manual': 'คู่มือการใช้งาน',
        'col_electric_drawing': 'แบบไฟฟ้า',
        'col_hydraulic_drawing': 'แบบไฮดรอลิก',
        'col_lubrication_std': 'ตารางมาตรฐานการหล่อลื่น',
        'col_relevant_item': 'รายการที่เกี่ยวข้อง',
        'col_category': 'หมวดหมู่',
        'col_applicable_oil': 'น้ำมันที่ใช้',
        'col_log_id': 'ID ประวัติ',
        'col_history_id': 'ID บันทึก',
        'col_created_at': 'วันที่สร้าง',
        'col_equipment_name': 'ชื่ออุปกรณ์',
        'col_status': 'สถานะ',
        'col_engineer': 'วิศวกร',
        'col_action': 'รายละเอียดงาน',
        'col_image_urls': 'URL รูปภาพที่แนบ',
        'no_active_sections': 'ไม่มีส่วนที่เปิดใช้งาน.',
        "product_name": "ชื่อผลิตภัณฑ์",
        "serial_number": "หมายเลขซีเรียล",
        "production_date": "วันที่ผลิต",
        "acquisition_cost": "ต้นทุนการได้มา",
        "acquisition_date": "วันที่ได้มา",
        "acquisition_basis": "เกณฑ์การได้มา",
        "purchase_date": "วันที่ซื้อ",
        "installation_location": "สถานที่ติดตั้ง",
        "equipment_grade": "ระดับอุปกรณ์",
        "min_mold_thickness": "ความหนาของแม่พิมพ์ขั้นต่ำ",
        "max_mold_thickness": "ความหนาของแม่พิมพ์สูงสุด",
        "tie_bar_spacing": "ระยะห่างของแกนยึด",
        "plate_thickness": "ความหนาของแผ่นเพลท",
        "oil_flow_rate": "อัตราการไหลของน้ำมัน",
        "max_displacement": "การเคลื่อนที่สูงสุด",
    },
    'es-MX': {
        'title': 'Sistema de Gestión de Equipos de Fábrica',
        'login_title': 'Iniciar sesión',
        'select_factory': 'Seleccionar fábrica',
        "equipment_age": "Edad del equipo",
        "years": "años transcurridos",
        'enter_password': 'Contraseña',
        'login_button': 'Iniciar sesión',
        'login_success': 'Inicio de sesión exitoso',
        'login_fail': 'Contraseña incorrecta',
        'current_factory': 'Fábrica actual',
        'logout': 'Cerrar sesión',
        'dashboard': 'Panel de control',
        'add_equipment': 'Añadir equipo',
        'add_maintenance_log': 'Añadir registro de mantenimiento',
        'view_maintenance_log': 'Ver registro de mantenimiento',
        'no_custom_sections': 'No hay configuraciones de secciones personalizadas.',
        'no_active_custom_sections': 'No hay secciones personalizadas activadas.',
        'record_status': 'Registrar estado',
        'no_specific_fields': 'No hay información de especificaciones dedicadas.',
        'admin_mode': 'Administrador',
        'custom_sections': 'Secciones personalizadas',
        'no_equipment_registered': 'No hay equipos registrados. Intente añadir uno nuevo.',
        'add_row_instruction': 'Presiona el botón '+' en la tabla para agregar una fila.',
        'capacity_specs': 'Capacidad y especificaciones',
        'motor_capacity_specs': 'Capacidad del MOTOR',
        'heater_capacity_specs': 'Capacidad del calentador',
        'total_weight': 'Peso total de la máquina (ton)',
        'status': 'Estado',
        'normal': 'Normal',
        'faulty': 'Defectuoso',
        'sold': 'Vendido',
        'change_status': 'Cambiar estado',
        'notes': 'Notas',
        'record_button': 'Registrar',
        'recent_maintenance_logs': 'Registros de mantenimiento recientes (máximo 5)',
        'no_recent_logs': 'No hay registros de mantenimiento recientes.',
        'equipment_name': 'Nombre del equipo',
        'maker': 'Fabricante',
        'model': 'Modelo',
        'details': 'Detalles',
        'upload_image': 'Imagen del equipo (se pueden seleccionar varias)',
        'add_equipment_button': 'Añadir equipo',
        'specific_fields': 'Especificaciones dedicadas',
        'add_success': 'Equipo añadido con éxito',
        'select_equipment': 'Seleccionar equipo para mantenimiento',
        'action_category': 'Categoría detallada del historial de mantenimiento',
        'electrical': 'Eléctrico',
        'mechanical': 'Mecánico',
        'drive': 'Transmisión',
        'other_category': 'Otro',
        'engineer_name': 'Nombre del ingeniero',
        'maintenance_action': 'Contenido del trabajo de mantenimiento',
        'maintenance_date': 'Fecha de mantenimiento',
        'maintenance_time': 'Hora de mantenimiento',
        'add_log_button': 'Añadir registro',
        'no_logs': 'No hay registros de mantenimiento para el equipo seleccionado.',
        'view_detail_log': 'Seleccionar un elemento para ver los detalles',
        'attachments': 'Archivos adjuntos',
        'no_attachments': 'No hay imágenes adjuntas.',
        'recent_status_history': 'Historial de estado reciente',
        'no_status_history': 'No hay historial de estado registrado.',
        'admin_password': 'Introduzca la contraseña de administrador',
        'admin_login_success': 'Inicio de sesión de administrador exitoso',
        'admin_login_fail': 'La contraseña de administrador es incorrecta.',
        'update_delete_equipment': 'Actualizar/Eliminar equipo',
        'select_equipment_admin': 'Seleccionar equipo para actualizar/eliminar',
        'update_button': 'Actualizar',
        'delete_button': 'Eliminar',
        'update_log_admin': 'Actualizar/Eliminar registro de mantenimiento',
        'select_log_admin': 'Seleccionar registro de mantenimiento para actualizar/eliminar',
        'update_status_admin': 'Actualizar/Eliminar historial de estado',
        'select_status_admin': 'Seleccionar historial de estado para actualizar/eliminar',
        'add_factory': 'Añadir fábrica',
        'factory_name': 'Nombre de la fábrica',
        'password': 'Contraseña',
        'add_factory_button': 'Añadir',
        'factory_update_delete': 'Actualizar/Eliminar fábrica',
        'select_factory_admin': 'Seleccionar fábrica para actualizar/eliminar',
        'update_success': 'La información del equipo ha sido actualizada.',
        'log_update_success': 'Registro de mantenimiento actualizado con éxito',
        'log_delete_success': 'Registro de mantenimiento eliminado con éxito',
        'status_update_success': 'El historial de estado ha sido actualizado.',
        'status_delete_success': 'El historial de estado ha sido eliminado.',
        'factory_add_success': 'Fábrica añadida con éxito',
        'factory_update_success': 'Información de la fábrica actualizada con éxito',
        'factory_delete_success': 'Fábrica eliminada con éxito',
        'basic_info': 'Información básica',
        'equipment_details': 'Detalles del equipo',
        'capacity_specs': 'Capacidad y especificaciones',
        'add_accessory_row': 'Añadir fila de accesorios',
        'accessory_specs': 'Especificaciones de accesorios',
        'add_spare_part_row': 'Añadir fila de piezas de repuesto',
        'spare_part_specs': 'Ciclo de reemplazo de piezas de repuesto',
        'add_document_row': 'Añadir fila de otros documentos',
        'documents': 'Otros documentos',
        'screw_specs': 'Ciclo de reemplazo y estándar de tornillos',
        'screw_material_specs': 'Especificaciones de material de tornillo',
        'screw_table_general': 'Tornillos generales',
        'screw_table_wear': 'Tornillos resistentes al desgaste',
        'oil_specs': 'Ciclo de reemplazo y estándar de aceite hidráulico',
        'oil_table_standard': 'Estándar y ciclo de reemplazo',
        'oil_notes': 'Plan de mantenimiento después de 1 año',
        'other_notes': 'Otras notas',
        'purchase_company': 'Empresa de compra',
        'spec': 'SPEC',
        'amount': 'Cantidad de aceite',
        'viscosity_date': 'Fecha de viscosidad',
        'viscosity_result': 'Resultado de la medición',
        'log_details': 'Detalles del registro de mantenimiento',
        'col_seq': 'Secuencia',
        'col_accessory_name': 'Nombre del accesorio',
        'col_accessory_type': 'Tipo',
        'col_accessory_serial': 'Número de serie de fabricación',
        'col_capacity_spec': 'Capacidad y especificaciones',
        'col_maker': 'Fabricante',
        'col_notes': 'Notas',
        'col_spare_part': 'PIEZA DE REPUESTO',
        'col_maintenance_cycle': 'Ciclo de mantenimiento',
        'col_replacement_date': 'Fecha de reemplazo',
        'col_doc_name': 'Nombre del documento técnico',
        'col_manual': 'Manual de instrucciones',
        'col_electric_drawing': 'Plano eléctrico',
        'col_hydraulic_drawing': 'Plano hidráulico',
        'col_lubrication_std': 'Tabla de estándar de lubricación',
        'col_relevant_item': 'Artículo relevante',
        'col_category': 'Categoría',
        'col_applicable_oil': 'Aceite aplicable',
        'col_log_id': 'ID Registro',
        'col_history_id': 'ID Historial',
        'col_created_at': 'Fecha de creación',
        'col_equipment_name': 'Nombre del equipo',
        'col_status': 'Estado',
        'col_engineer': 'Ingeniero',
        'col_action': 'Contenido del trabajo',
        'col_image_urls': 'URL de imágenes adjuntas',
        'no_active_sections': 'No hay secciones activadas.',
        "product_name": "Nombre del producto",
        "serial_number": "Número de serie",
        "production_date": "Fecha de producción",
        "acquisition_cost": "Costo de adquisición",
        "acquisition_date": "Fecha de adquisición",
        "acquisition_basis": "Base de adquisición",
        "purchase_date": "Fecha de compra",
        "installation_location": "Ubicación de la instalación",
        "equipment_grade": "Grado de equipo",
        "min_mold_thickness": "Espesor mínimo del molde",
        "max_mold_thickness": "Espesor máximo del molde",
        "tie_bar_spacing": "Espacio entre barras de sujeción",
        "plate_thickness": "Espesor de la placa",
        "oil_flow_rate": "Tasa de flujo de aceite",
        "max_displacement": "Desplazamiento máximo",
    }
}

def get_translation(key):
    lang = st.session_state.get('language', 'ko')
    return TRANSLATIONS.get(lang, TRANSLATIONS['ko']).get(key, key)

def set_language(lang):
    st.session_state['language'] = lang
    st.rerun()

# 추가 세션 상태 초기화
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
if 'current_factory' not in st.session_state:
    st.session_state['current_factory'] = None
if 'selected_eq_id_admin' not in st.session_state:
    st.session_state['selected_eq_id_admin'] = None
if 'selected_log_id_admin' not in st.session_state:
    st.session_state['selected_log_id_admin'] = None
if 'selected_factory_id_admin' not in st.session_state:
    st.session_state['selected_factory_id_admin'] = None
if 'selected_status_id_admin' not in st.session_state:
    st.session_state['selected_status_id_admin'] = None
if 'selected_log_id' not in st.session_state:
    st.session_state['selected_log_id'] = None
if 'accessory_specs' not in st.session_state:
    st.session_state.accessory_specs = []
if 'edit_accessory_specs' not in st.session_state:
    st.session_state.edit_accessory_specs = []
if 'spare_part_specs' not in st.session_state:
    st.session_state.spare_part_specs = []
if 'edit_spare_part_specs' not in st.session_state:
    st.session_state.edit_spare_part_specs = []
if 'documents' not in st.session_state:
    st.session_state.documents = []
if 'edit_documents' not in st.session_state:
    st.session_state.edit_documents = []
if 'selected_eq_id_admin_temp' not in st.session_state:
    st.session_state.selected_eq_id_admin_temp = None
if 'language' not in st.session_state:
    st.session_state.language = 'ko'
if 'edit_oil_specs' not in st.session_state:
    st.session_state.edit_oil_specs = []
if 'edit_screw_specs' not in st.session_state:
    st.session_state.edit_screw_specs = {}
if 'edit_oil_notes' not in st.session_state:
    st.session_state.edit_oil_notes = ''
if 'edit_oil_aftercare' not in st.session_state:
    st.session_state.edit_oil_aftercare = ''

def reset_add_equipment_form_state():
    if 'accessory_specs' in st.session_state:
        st.session_state.accessory_specs = []
    if 'spare_part_specs' in st.session_state:
        st.session_state.spare_part_specs = []
    if 'documents' in st.session_state:
        st.session_state.documents = []
    if 'oil_specs' in st.session_state:
        st.session_state.oil_specs = [
            {"구분": "표준", "적용 작동유 SPCE": "LG 정유", "교체 주기": "9000HR / 1년"},
            {"구분": "SPCE", "적용 작동유 SPCE": "란도 HD 46", "교체 주기": "375일"}
        ]
    if 'oil_notes' in st.session_state:
        st.session_state.oil_notes = ''
    if 'oil_aftercare' in st.session_state:
        st.session_state.oil_aftercare = ''
    if 'screw_specs' in st.session_state:
        st.session_state.screw_specs = {
            'material_spec_description': """A:일반 수지류(PP.PE.ABS.POM.PMMA.PC.PET)
B:GLASS WOOL 포함율 30% 이내(PC-GF,POM-GF,PA-GF,PBT-GF)
C:GLASS WOOL 포함율 30% 이상(난연 ABS, 난연PC,난연 PBI, NYLON6,66)
D:400℃이상 온도 사용 제품""",
            'screw_type_general': '일반 수지용 SCREW',
            'applicable_general': '',
            'screw_type_wear': '내마모성 SCREW',
            'applicable_wear': '',
            'general_cycle': [{'해당 사양': '교체 주기 (월)', 'A': '5', 'B': '5', 'C': '3', 'D': '3'}],
            'wear_resistant_cycle': [{'해당 사양': '교체 주기 (월)', 'A': '10', 'B': '10', 'C': '5', 'D': '5'}]
        }
    if 'custom_sections' in st.session_state:
        st.session_state.custom_sections = {}

def set_selected_equipment():
    selected_name = st.session_state.get('selected_equipment_name_admin_selectbox')
    if not selected_name or selected_name == '설비를 선택하세요':
        st.session_state.selected_eq_id_admin = None
        st.session_state.edit_accessory_specs = []
        st.session_state.edit_spare_part_specs = []
        st.session_state.edit_documents = []
        st.session_state.edit_oil_specs = []
        st.session_state.edit_screw_specs = {}
        st.session_state.edit_oil_notes = ''
        st.session_state.edit_oil_aftercare = ''
        return

    equipment_list_admin = get_equipment()
    eq_data = next((eq for eq in equipment_list_admin if eq['name'] == selected_name), None)
    
    if eq_data:
        st.session_state.selected_eq_id_admin = eq_data['id']
        try:
            st.session_state.edit_accessory_specs = json.loads(eq_data.get('accessory_specs') or '[]')
        except:
            st.session_state.edit_accessory_specs = []
        try:
            st.session_state.edit_spare_part_specs = json.loads(eq_data.get('spare_part_specs') or '[]')
        except:
            st.session_state.edit_spare_part_specs = []
        try:
            st.session_state.edit_documents = json.loads(eq_data.get('documents') or '[]')
        except:
            st.session_state.edit_documents = []
        try:
            oil_specs_data = json.loads(eq_data.get('oil_specs') or '[]')
            st.session_state.edit_oil_specs = [item for item in oil_specs_data if 'notes' not in item and 'aftercare' not in item]
            st.session_state.edit_oil_notes = next((item['notes'] for item in oil_specs_data if 'notes' in item), '')
            st.session_state.edit_oil_aftercare = next((item['aftercare'] for item in oil_specs_data if 'aftercare' in item), '')
        except:
            st.session_state.edit_oil_specs = []
            st.session_state.edit_oil_notes = ''
            st.session_state.edit_oil_aftercare = ''
        
        try:
            screw_data = json.loads(eq_data.get('screw_specs') or '{}')
            if not isinstance(screw_data, dict):
                screw_data = {}
            general_cycle_data = screw_data.get('general_cycle', [{'해당 사양': '교체 주기 (월)', 'A': '5', 'B': '5', 'C': '3', 'D': '3'}])
            wear_cycle_data = screw_data.get('wear_resistant_cycle', [{'해당 사양': '교체 주기 (월)', 'A': '10', 'B': '10', 'C': '5', 'D': '5'}])
            st.session_state.edit_screw_specs = {
                'material_spec_description': screw_data.get('material_spec_description', ''),
                'screw_type_general': screw_data.get('screw_type_general', ''),
                'applicable_general': screw_data.get('applicable_general', ''),
                'screw_type_wear': screw_data.get('screw_type_wear', ''),
                'applicable_wear': screw_data.get('applicable_wear', ''),
                'general_cycle_df': pd.DataFrame(general_cycle_data),
                'wear_resistant_cycle_df': pd.DataFrame(wear_cycle_data)
            }
        except:
            st.session_state.edit_screw_specs = {
                'material_spec_description': '',
                'screw_type_general': '',
                'applicable_general': '',
                'screw_type_wear': '',
                'applicable_wear': '',
                'general_cycle_df': pd.DataFrame([{'해당 사양': '교체 주기 (월)', 'A': '5', 'B': '5', 'C': '3', 'D': '3'}]),
                'wear_resistant_cycle_df': pd.DataFrame([{'해당 사양': '교체 주기 (월)', 'A': '10', 'B': '10', 'C': '5', 'D': '5'}])
            }
    else:
        st.session_state.selected_eq_id_admin = None

def set_selected_log_admin():
    if 'selected_log_id_admin_selectbox' in st.session_state:
        selected_display = st.session_state.selected_log_id_admin_selectbox
        if selected_display and selected_display != '이력을 선택하세요':
            try:
                selected_id = int(selected_display.split('ID: ')[1].split(' |')[0])
                st.session_state.selected_log_id_admin = selected_id
            except (IndexError, ValueError):
                st.session_state.selected_log_id_admin = None
        else:
            st.session_state.selected_log_id_admin = None

def set_selected_factory():
    if 'selected_factory_name_admin_selectbox' in st.session_state:
        factories_list_admin = get_factories()
        factory_data = next(
            (f for f in factories_list_admin if f['name'] == st.session_state.selected_factory_name_admin_selectbox),
            None)
        if factory_data:
            st.session_state.selected_factory_id_admin = factory_data['id']
        else:
            st.session_state.selected_factory_id_admin = None

def set_selected_status_history():
    if 'selected_status_id_admin_selectbox' in st.session_state:
        selected_display = st.session_state.selected_status_id_admin_selectbox
        if selected_display and selected_display != '기록을 선택하세요':
            try:
                selected_id = int(selected_display.split('ID: ')[1].split(' |')[0])
                st.session_state.selected_status_id_admin = selected_id
            except (IndexError, ValueError):
                st.session_state.selected_status_id_admin = None
        else:
            st.session_state.selected_status_id_admin = None

def set_selected_log():
    if 'selected_log_name_view_selectbox' in st.session_state:
        logs_list = get_maintenance_logs()
        log_data = next((log for log in logs_list if log['id'] == st.session_state.selected_log_name_view_selectbox), None)
        if log_data:
            st.session_state.selected_log_id = log_data['id']
        else:
            st.session_state.selected_log_id = None

# ------------------------------------------------------
# Streamlit UI
# ------------------------------------------------------
st.set_page_config(page_title=get_translation('title'), layout="wide")

# 언어 선택 버튼
header_cols = st.columns([1, 1, 1, 0.1, 0.1, 0.1, 0.1])
with header_cols[3]:
    if st.button('🇰🇷', key='lang_ko_btn'): set_language('ko')
with header_cols[4]:
    if st.button('🇻🇳', key='lang_vi_btn'): set_language('vi')
with header_cols[5]:
    if st.button('🇹🇭', key='lang_th_btn'): set_language('th')
with header_cols[6]:
    if st.button('🇪🇸', key='lang_es_btn'): set_language('es-MX')

# 로그인 화면
if not st.session_state['authenticated']:
    # 회사 로고를 타이틀 위로 이동
    logo_url = "https://xvudytcfwnzjxhaortik.supabase.co/storage/v1/object/public/equipment_images/logo_image/logo.png"
    st.image(logo_url, width=200)  # use_column_width 대체
    
    # 배경 이미지 CSS 설정
    background_url = "https://xvudytcfwnzjxhaortik.supabase.co/storage/v1/object/public/equipment_images/logo_image/background.png"
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-image: url("{background_url}");
            background-size: contain;
            background-repeat: no-repeat;
            background-position: right center;  /* 배경을 오른쪽으로 정렬 */
            background-attachment: fixed;
            min-height: 100vh;
        }}
        @media (max-width: 600px) {{
            .stApp {{
                background-size: cover;
                background-attachment: scroll;
                background-position: center;  /* 모바일에서는 중앙으로 */
            }}
        }}
        .stImage {{
            margin-bottom: 20px;
            margin-top: 10px;
            display: block;
            margin-left: auto;
            margin-right: auto;
        }}
        @media (max-width: 600px) {{
            .stImage > img {{
                width: 120px !important;
            }}
        }}
        .stApp > div {{
            background-color: rgba(255, 255, 255, 0.7);
            padding: 20px;
            border-radius: 10px;
            max-width: 1000px;  /* 너비 2배로 늘림 */
            margin: 0;  /* 왼쪽 정렬 */
            margin-left: 0;  /* 왼쪽 여백 0 */
        }}
        @media (max-width: 600px) {{
            .stApp > div {{
                max-width: 90%;
                padding: 10px;
                margin-left: 0;  /* 모바일에서도 왼쪽 정렬 */
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True
    )
    
    st.title(get_translation('title') + ' - ' + get_translation('login_title'))
    
    factories_list = get_factories()
    factory_names = [f['name'] for f in factories_list]

    with st.form("login_form"):
        selected_factory = st.selectbox(get_translation('select_factory'), ['공장을 선택하세요'] + factory_names)
        password = st.text_input(get_translation('enter_password'), type="password")
        if st.form_submit_button(get_translation('login_button')):
            if selected_factory == '공장을 선택하세요':
                st.error("공장을 선택하세요.")
            else:
                factory_data = next((f for f in factories_list if f['name'] == selected_factory), None)
                if factory_data and password == factory_data['password']:
                    st.session_state.authenticated = True
                    st.session_state.current_factory = factory_data
                    st.success(get_translation('login_success'))
                    st.rerun()
                else:
                    st.error(get_translation('login_fail'))
else:
    factory_id = st.session_state.current_factory['id']
    factory_name = st.session_state.current_factory['name']
    st.title(get_translation('title') + f" - {factory_name}")

    # 탭 초기화
    tabs = st.tabs([
        get_translation('dashboard'),
        get_translation('add_equipment'),
        get_translation('add_maintenance_log'),
        get_translation('view_maintenance_log'),
        get_translation('record_status'),
        get_translation('admin_mode')
    ])

# ------------------------ 대시보드 ------------------------
    with tabs[0]:
        st.header(get_translation('dashboard'))
        equipment_search = st.text_input("설비 검색", placeholder="설비 이름, 제조사, 모델, 상태로 검색...", key="dashboard_eq_search")
        equipment_list = get_equipment(factory_id)
        if equipment_search:
            filtered_equipment = [eq for eq in equipment_list if
                                 equipment_search.lower() in eq['name'].lower() or
                                 equipment_search.lower() in eq.get('maker', '').lower() or
                                 equipment_search.lower() in eq.get('model', '').lower() or
                                 equipment_search.lower() in eq.get('status', '').lower()]
        else:
            filtered_equipment = equipment_list
        if not filtered_equipment:
            st.info(get_translation('no_equipment_registered'))
        else:
            for eq in filtered_equipment:
                status_color = "green" if eq.get('status') == '정상' else "red" if eq.get('status') == '고장' else "orange"  # 매각에 orange 색상 추가
                status_text = get_translation('normal') if eq.get('status') == '정상' else get_translation('faulty') if eq.get('status') == '고장' else get_translation('sold')
                with st.expander(
                        f"[{status_text}] {eq['name']} ({eq.get('model', '')})",
                        expanded=False):
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        # 이미지 표시
                        if eq.get('image_urls'):
                            image_urls = eq['image_urls'].split(',') if isinstance(eq['image_urls'], str) else []
                            if image_urls:
                                for url in image_urls:
                                    url = url.strip()
                                    try:
                                        st.image(url, width=300, caption=f"{eq['name']} 이미지")
                                    except Exception as e:
                                        st.warning(f"이미지 로드 실패 ({url}): {str(e)}")
                            else:
                                st.warning(get_translation('no_valid_image_urls'))
                        else:
                            st.warning(get_translation('no_attachments'))
                        
                        # 상태 변경 폼
                        st.subheader(get_translation('record_status'))
                        with st.form(f"status_form_{eq['id']}", clear_on_submit=True):
                            history_date = st.date_input(get_translation('maintenance_date'), value=date.today())
                            history_time = st.time_input(get_translation('maintenance_time'), value=time(datetime.now().hour, datetime.now().minute))
                            new_status = st.radio(get_translation('change_status'), [f'🟢 {get_translation("normal")}', f'🔴 {get_translation("faulty")}', f'💰 {get_translation("sold")}'], index=0 if eq.get('status') == '정상' else 1 if eq.get('status') == '고장' else 2)
                            notes = st.text_area(get_translation('notes'))
                            if st.form_submit_button(get_translation('record_button')):
                                if new_status.startswith('🟢'):
                                    final_status = '정상'
                                elif new_status.startswith('🔴'):
                                    final_status = '고장'
                                elif new_status.startswith('💰'):
                                    final_status = '매각'
                                add_status_history(eq['id'], final_status, notes, history_date, history_time)
                                st.rerun()
                    with col2:
                        # 설비 상세 정보 (통합 표시)
                        st.subheader(get_translation('equipment_details'))

                        # 연식 계산 및 강조 표시
                        production_date_str = eq.get('production_date', 'N/A')
                        if production_date_str and production_date_str != 'N/A':
                            production_date = get_date_value(production_date_str)
                            if production_date:
                                current_date = date.today()
                                years = current_date.year - production_date.year
                                # 월/일을 고려한 정확한 연식 계산
                                if (current_date.month, current_date.day) < (production_date.month, production_date.day):
                                    years -= 1
                                st.markdown(
                                    f"<b>{get_translation('equipment_age')}:</b> {years} {get_translation('years')}",
                                    unsafe_allow_html=True
                                )
                            else:
                                st.markdown(
                                    f"<b>{get_translation('equipment_age')}:</b> {get_translation('not_available')}",
                                    unsafe_allow_html=True
                                )
                        else:
                            st.markdown(
                                f"<b>{get_translation('equipment_age')}:</b> {get_translation('not_available')}",
                                unsafe_allow_html=True
                            )
        
                        try:
                            # details JSON 로드
                            raw_details = eq.get('details')
                            details = raw_details if isinstance(raw_details, dict) else json.loads(raw_details if raw_details else '{}')

                            # fields_config 로드
                            raw_fields_config = eq.get('fields_config')
                            if raw_fields_config is None:
                                fields_config = {}
                            elif isinstance(raw_fields_config, dict):
                                fields_config = raw_fields_config
                            else:
                                fields_config = json.loads(str(raw_fields_config) if raw_fields_config else '{}')

                            all_fields = get_field_definitions()
                            
                            # === 1. 기본 정보 (2열 레이아웃) ===
                            with st.container():
                                details_list = [
                                    (get_translation('maker'), eq.get('maker', 'N/A')),
                                    (get_translation('model'), eq.get('model', 'N/A')),
                                    (get_translation('status'), eq.get('status', 'N/A')),
                                    (get_translation('product_name'), eq.get('product_name', 'N/A')),
                                    (get_translation('serial_number'), eq.get('serial_number', 'N/A')),
                                    (get_translation('production_date'), eq.get('production_date', 'N/A')),
                                    (get_translation('acquisition_cost'), eq.get('acquisition_cost', 'N/A')),
                                    (get_translation('acquisition_date'), eq.get('acquisition_date', 'N/A')),
                                    (get_translation('acquisition_basis'), eq.get('acquisition_basis', 'N/A')),
                                    (get_translation('purchase_date'), eq.get('purchase_date', 'N/A')),
                                    (get_translation('installation_location'), eq.get('installation_location', 'N/A')),
                                    (get_translation('equipment_grade'), eq.get('equipment_grade', 'N/A')),
                                    (get_translation('motor_capacity_specs'), eq.get('motor_capacity', 'N/A')),
                                    (get_translation('heater_capacity_specs'), eq.get('heater_capacity', 'N/A')),
                                    (get_translation('total_weight'), eq.get('total_weight', 'N/A')),
                                ]

                                cols = st.columns(2)
                                for i, (label, value) in enumerate(details_list):
                                    with cols[i % 2]:
                                        st.write(f"**{label}:** {value}")

                            # === 2. 특화 필드 추가 (equipment 테이블에서 직접 가져오기) ===
                            with st.container():
                                specific_field_keys = fields_config.get('specific_fields', [])
                                if specific_field_keys:
                                    st.subheader(get_translation('specific_fields'))
                                    specific_details = []
                                    for field_key in specific_field_keys:
                                        field_def = FIELD_DEFINITIONS.get(field_key, {'label': field_key, 'type': 'text'})
                                        field_value = eq.get(field_key, '') or details.get(field_key, '')
                                        if field_value and str(field_value).strip() and str(field_value) != 'N/A':
                                            translated_label = get_translation(field_def['label'])
                                            specific_details.append((translated_label, field_value))

                                    if specific_details:
                                        # 2열 레이아웃으로 표시
                                        cols = st.columns(2)
                                        for i, (label, value) in enumerate(specific_details):
                                            with cols[i % 2]:
                                                # 긴 텍스트는 줄바꿈 적용
                                                if isinstance(value, str) and '\n' in value:
                                                    st.markdown(f"**{label}:**")
                                                    st.markdown(value.replace('\n', '  \n'))
                                                else:
                                                    st.markdown(f"**{label}:** {value}")
                                    else:
                                        st.info(get_translation('no_specific_fields'))
                                else:
                                    st.info(get_translation('no_specific_fields'))
                    
                            # === 3. 커스텀 섹션 필드 추가 (텍스트 형태) - 별도로 표시 ===
                            default_sections = ['has_accessory_specs', 'has_spare_part_specs', 'has_screw_specs', 'has_oil_specs', 'has_documents']
                            custom_section_list = []

                            for config_key, config_value in fields_config.items():
                                if config_key.startswith('has_') and config_value == True and config_key not in default_sections and config_key != 'has_other_notes':
                                    section_key = config_key.replace('has_', '')
                                    field_def = next((f for f in all_fields if f['field_key'] == section_key), None)
                                    if field_def:
                                        custom_value = eq.get(section_key, '') or details.get(section_key, '')
                                        if custom_value and str(custom_value).strip():
                                            custom_section_list.append((field_def['field_label'], custom_value))

                            # 커스텀 섹션이 있을 경우에만 표시
                            if custom_section_list:
                                st.markdown("---")
                                st.subheader("추가 정보")
                                cols = st.columns(2)
                                for i, (label, value) in enumerate(custom_section_list):
                                    with cols[i % 2]:
                                        # 긴 텍스트는 줄바꿈 적용
                                        if isinstance(value, str) and '\n' in value:
                                            st.markdown(f"**{label}:**")
                                            st.markdown(value.replace('\n', '  \n'))
                                        else:
                                            st.markdown(f"**{label}:** {value}")
                    
                            # === 4. 기타사항 추가 ===
                            other_notes = eq.get('other_notes', '') or details.get('other_notes', '')
                            if other_notes and str(other_notes).strip():
                                st.markdown("---")
                                st.subheader(get_translation('other_notes'))
                                st.markdown(other_notes.replace('\n', '  \n'))
                    
                            # === 5. 테이블 형태 섹션 (선택적 섹션들) - 항상 제목 표시 ===
                            st.markdown("---")
                            st.markdown("##### 📋 상세 사양")
                    
                            # 부속기기
                            if fields_config.get('has_accessory_specs', False):
                                st.markdown(f"**{get_translation('accessory_specs')}**")
                                accessory_data = eq.get('accessory_specs', [])
                                if isinstance(accessory_data, str):
                                    accessory_data = json.loads(accessory_data if accessory_data else '[]')
                                if accessory_data:
                                    df = pd.DataFrame(accessory_data)
                                    df = df.rename(columns={
                                        '순번': get_translation('col_seq'),
                                        '부속기기 명': get_translation('col_accessory_name'),
                                        '형식': get_translation('col_accessory_type'),
                                        '제작번호': get_translation('col_accessory_serial'),
                                        '용량 및 규격': get_translation('col_capacity_spec'),
                                        '제조처': get_translation('col_maker'),
                                        '비고': get_translation('col_notes')
                                    })
                                    st.dataframe(df, width='stretch')
                                else:
                                    st.info("등록된 부속기기가 없습니다.")
                                st.markdown("")
                    
                            # SPARE PART
                            if fields_config.get('has_spare_part_specs', False):
                                st.markdown(f"**{get_translation('spare_part_specs')}**")
                                spare_data = eq.get('spare_part_specs', [])
                                if isinstance(spare_data, str):
                                    spare_data = json.loads(spare_data if spare_data else '[]')
                                if spare_data:
                                    df = pd.DataFrame(spare_data)
                                    df = df.rename(columns={
                                        'SPARE PART': get_translation('col_spare_part'),
                                        '교체 주기': get_translation('col_maintenance_cycle'),
                                        '교체 일자': get_translation('col_replacement_date')
                                    })
                                    st.dataframe(df, width='stretch')
                                else:
                                    st.info("등록된 SPARE PART가 없습니다.")
                                st.markdown("")
                    
                            # 스크류 사양
                            if fields_config.get('has_screw_specs', False):
                                st.markdown(f"**{get_translation('screw_specs')}**")
                                screw_data = eq.get('screw_specs', {})
                                if isinstance(screw_data, str):
                                    screw_data = json.loads(screw_data if screw_data else '{}')
                                if screw_data and (screw_data.get('material_spec_description') or screw_data.get('general_cycle') or screw_data.get('wear_resistant_cycle')):
                                    if screw_data.get('material_spec_description'):
                                        st.markdown("*재료 사양:*")
                                        # 원본 줄바꿈 유지
                                        material_spec = screw_data['material_spec_description']
                                        st.text(material_spec)
                                    if screw_data.get('general_cycle'):
                                        st.markdown("*일반용 SCREW 교체 주기*")
                                        df_general = pd.DataFrame(screw_data['general_cycle'])
                                        st.dataframe(df_general, width='stretch')
                                    if screw_data.get('wear_resistant_cycle'):
                                        st.markdown("*내마모성 SCREW 교체 주기*")
                                        df_wear = pd.DataFrame(screw_data['wear_resistant_cycle'])
                                        st.dataframe(df_wear, width='stretch')
                                else:
                                    st.info("등록된 스크류 사양이 없습니다.")
                                st.markdown("")
                    
                            # 작동유
                            if fields_config.get('has_oil_specs', False):
                                st.markdown(f"**{get_translation('oil_specs')}**")
                                oil_data = eq.get('oil_specs', [])
                                if isinstance(oil_data, str):
                                    oil_data = json.loads(oil_data if oil_data else '[]')
                                oil_specs_only = [item for item in oil_data if 'notes' not in item and 'aftercare' not in item]
                                if oil_specs_only:
                                    df = pd.DataFrame(oil_specs_only)
                                    df = df.rename(columns={
                                        '구분': get_translation('col_category'),
                                        '적용 작동유 SPCE': get_translation('col_applicable_oil'),
                                        '교체 주기': get_translation('col_maintenance_cycle')
                                    })
                                    st.dataframe(df, width='stretch')
                                
                                    # oil_notes와 aftercare
                                    oil_notes = next((item['notes'] for item in oil_data if 'notes' in item), '')
                                    oil_aftercare = next((item['aftercare'] for item in oil_data if 'aftercare' in item), '')
                                    if oil_notes:
                                        st.markdown(f"*{oil_notes}*")
                                    if oil_aftercare and oil_aftercare.strip():
                                        st.markdown(f"*1년 경과 후:*  \n{oil_aftercare.replace(chr(10), '  ' + chr(10))}")
                                else:
                                    st.info("등록된 작동유 정보가 없습니다.")
                                st.markdown("")
                    
                            # 문서
                            st.markdown(f"**{get_translation('documents')}**")
                            doc_data = eq.get('documents', [])
                            if isinstance(doc_data, str):
                                doc_data = json.loads(doc_data if doc_data else '[]')
                            # 중복 제거 (이름 기반)
                            unique_doc_data = {d['기술 자료명']: d for d in doc_data}.values()  # 이름 중복 시 마지막 항목만 유지
                            if unique_doc_data:
                                for item in unique_doc_data:
                                    doc_name = item.get(get_translation('col_doc_name'), 'Unnamed Document')
                                    doc_url = item.get('url')
                                    if doc_url:
                                        st.write(f"문서: {doc_name}")
                                        st.download_button(
                                            label=f"다운로드 {doc_name}",
                                            data=requests.get(doc_url).content,
                                            file_name=doc_name,
                                            mime=item.get('file_type', 'application/octet-stream'),
                                            key=f"download_doc_{uuid.uuid4().hex}_{eq['id']}"
                                        )
                            else:
                                st.info("등록된 문서가 없습니다.")

                        except Exception as e:
                            st.error(f"설비 정보 표시 중 오류: {str(e)}")
                            import traceback
                            st.error(traceback.format_exc())

                    # 최근 정비 이력
                    st.markdown("---")
                    st.subheader(get_translation('recent_maintenance_logs'))
                    maintenance_logs = get_maintenance_logs(equipment_id=eq['id'])
                    if maintenance_logs:
                        recent_logs = maintenance_logs[:5]
                        log_df = pd.DataFrame(recent_logs)
                        st.dataframe(
                            log_df.rename(columns={
                                'id': get_translation('col_log_id'),
                                'maintenance_date': get_translation('maintenance_date'),
                                'engineer': get_translation('col_engineer'),
                                'action': get_translation('col_action'),
                                'action_category': get_translation('action_category'),  # 추가
                                'notes': get_translation('col_notes'),
                                'image_urls': get_translation('col_image_urls')
                                # 'equipment_name': get_translation('col_equipment_name')  # 필요 시 주석 해제
                            })[[
                                get_translation('col_log_id'),
                                get_translation('maintenance_date'),
                                get_translation('col_engineer'),
                                get_translation('action_category'),  # 추가
                                get_translation('col_action'),
                                get_translation('col_notes'),
                                get_translation('col_image_urls')
                                # get_translation('col_equipment_name'),  # 필요 시 주석 해제
                            ]],
                            width='stretch',
                            hide_index=True
                        )
                    else:
                        st.info(get_translation('no_recent_logs'))

                    # 최근 상태 이력
                    st.markdown("---")
                    st.subheader(get_translation('recent_status_history'))
                    status_history = get_status_history(equipment_id=eq['id'])
                    if status_history:
                        status_df = pd.DataFrame(status_history)
                        st.dataframe(
                            status_df.rename(columns={
                                'id': get_translation('col_history_id'),
                                'created_at': get_translation('col_created_at'),
                                'status': get_translation('col_status'),
                                'notes': get_translation('col_notes')
                            })[[get_translation('col_history_id'), get_translation('col_created_at'),
                                get_translation('col_status'), get_translation('col_notes')]],
                            width='stretch'
                        )
                    else:
                        st.info(get_translation('no_status_history'))
    
# ------------------------ 설비 추가 ------------------------
    with tabs[1]:
        st.header(get_translation('add_equipment'))
    
        # 내용 초기화 버튼 (상단에 배치)
        if st.button(get_translation('reset_content'), key="reset_add_form"):
            # 모든 세션 상태 초기화
            st.session_state.accessory_specs = []
            st.session_state.spare_part_specs = []
            st.session_state.documents = []
            st.session_state.screw_specs = {
                'screw_type_general': '일반 수지용 SCREW',
                'applicable_general': '',
                'screw_type_wear': '내 마모성 SCREW',
                'applicable_wear': '',
                'material_spec_description': '',
                'general_cycle': [],
                'wear_resistant_cycle': []
            }
            st.session_state.oil_specs = []
            st.session_state.custom_sections = {}
            st.session_state.other_notes = ''
            st.session_state.oil_aftercare = ''
            # 텍스트 입력 필드 리셋 (키를 사용해 강제 초기화, 하지만 Streamlit에서 키 기반 입력은 rerun 시 유지되므로 세션으로 관리)
            st.session_state.add_eq_name = ''
            st.session_state.add_eq_product_name = ''
            st.session_state.add_eq_maker = ''
            st.session_state.add_eq_model = ''
            st.session_state.add_eq_serial_number = ''
            st.session_state.add_eq_production_date = None
            st.session_state.add_eq_acquisition_cost = ''
            st.session_state.add_eq_acquisition_date = None
            st.session_state.add_eq_acquisition_basis = ''
            st.session_state.add_eq_purchase_date = None
            st.session_state.add_eq_installation_location = ''
            st.session_state.add_eq_motor_capacity = ''
            st.session_state.add_eq_heater_capacity = ''
            st.session_state.add_eq_total_weight = ''
            # 특화 필드 등은 동적이라 별도 리셋 불필요
            st.success("입력 내용이 초기화되었습니다.")
            st.rerun()
    
        # 설비 템플릿 로드
        templates = get_equipment_templates()
        template_options = {t['display_name']: t for t in templates}
    
        # 설비 타입 선택
        selected_template_name = st.selectbox(
            "🔧 설비 종류를 선택하세요",
            options=['선택하세요'] + list(template_options.keys()),
            key="equipment_type_selector"
        )
    
        if selected_template_name != '선택하세요':
            selected_template = template_options[selected_template_name]
            fields_config = selected_template['fields_config']
    
            # 세션 상태 초기화 (타입 선택 시 KeyError 방지 및 빈 상태로 시작, 하지만 기존 값 유지 위해 처음에만)
            if 'accessory_specs' not in st.session_state:
                st.session_state.accessory_specs = []
            if 'spare_part_specs' not in st.session_state:
                st.session_state.spare_part_specs = []
            if 'documents' not in st.session_state:
                st.session_state.documents = []
            if 'screw_specs' not in st.session_state:
                st.session_state.screw_specs = {
                    'screw_type_general': '일반 수지용 SCREW',
                    'applicable_general': '',
                    'screw_type_wear': '내 마모성 SCREW',
                    'applicable_wear': '',
                    'material_spec_description': '',
                    'general_cycle': [],
                    'wear_resistant_cycle': []
                }
            if 'oil_specs' not in st.session_state:
                st.session_state.oil_specs = []
            if 'custom_sections' not in st.session_state:
                st.session_state.custom_sections = {}
            if 'other_notes' not in st.session_state:
                st.session_state.other_notes = ''
            if 'oil_aftercare' not in st.session_state:
                st.session_state.oil_aftercare = ''
        
            with st.form("add_equipment_form"):
                st.markdown(f"##### {get_translation('basic_info')}")
            
                # ========== 공통 필드 (모든 설비에 공통) ==========
                # 첫 번째 행: 설비명, 제품명, 제조사
                col1, col2, col3 = st.columns(3)
                with col1:
                    name = st.text_input(get_translation('equipment_name'), key="add_eq_name")
                with col2:
                    product_name = st.text_input(get_translation('product_name'), key="add_eq_product_name")
                with col3:
                    maker = st.text_input(get_translation('maker'), key="add_eq_maker")

                # 두 번째 행: 모델명, 시리얼번호, 제작일
                col4, col5, col6 = st.columns(3)
                with col4:
                    model = st.text_input(get_translation('model'), key="add_eq_model")
                with col5:
                    serial_number = st.text_input(get_translation('serial_number'), key="add_eq_serial_number")
                with col6:
                    production_date = st.date_input(get_translation('production_date'), key="add_eq_production_date", min_value=date(1950, 1, 1))

                # 세 번째 행: 취득가액, 취득일, 취득근거
                col7, col8, col9 = st.columns(3)
                with col7:
                    acquisition_cost = st.text_input(get_translation('acquisition_cost'), key="add_eq_acquisition_cost")
                with col8:
                    acquisition_date = st.date_input(get_translation('acquisition_date'), key="add_eq_acquisition_date", min_value=date(1950, 1, 1))
                with col9:
                    acquisition_basis = st.text_input(get_translation('acquisition_basis'), key="add_eq_acquisition_basis")

                # 네 번째 행: 구입일, 설치장소, 설비 등급
                col10, col11, col12 = st.columns(3)
                with col10:
                    purchase_date = st.date_input(get_translation('purchase_date'), key="add_eq_purchase_date", min_value=date(1950, 1, 1))
                with col11:
                    installation_location = st.text_input(get_translation('installation_location'), key="add_eq_installation_location")
                with col12:
                    equipment_grade = st.text_input(get_translation('equipment_grade'), key="add_eq_equipment_grade")

                # 다섯 번째 행: 모터용량, 히터용량, 총중량
                col13, col14, col15 = st.columns(3)
                with col13:
                    motor_capacity = st.text_input(get_translation('motor_capacity_specs'), key="add_eq_motor_capacity")
                with col14:
                    heater_capacity = st.text_input(get_translation('heater_capacity_specs'), key="add_eq_heater_capacity")
                with col15:
                    total_weight = st.text_input(get_translation('total_weight'), key="add_eq_total_weight")
            
                st.markdown("---")
            
                # ========== 설비 타입별 특화 필드 (동적으로 표시) ==========
                specific_fields = fields_config.get('specific_fields', [])
                if specific_fields:
                    st.markdown(f"##### {selected_template_name} 전용 사양")
                    specific_fields_data = {}
                    for i in range(0, len(specific_fields), 3):
                        cols = st.columns(3)
                        for j in range(3):
                            idx = i + j
                            if idx < len(specific_fields):
                                field_key = specific_fields[idx]
                                field_def = FIELD_DEFINITIONS.get(field_key, {'label': field_key, 'type': 'text'})
                                with cols[j]:
                                    value = st.text_input(get_translation(field_key), key=f"add_spec_{field_key}")
                                    if value.strip():  # 빈 값 제외
                                        specific_fields_data[field_key] = value
                    st.markdown("---")
            
                # ========== 조건부 섹션들 ==========
            
                # 부속기기 사양
                if fields_config.get('has_accessory_specs', True):
                    with st.expander(get_translation('accessory_specs'), expanded=False):
                        st.markdown(f"**{get_translation('add_row_instruction')}**")
                        accessory_df = pd.DataFrame(
                            st.session_state.accessory_specs if st.session_state.accessory_specs else [],
                            columns=['순번', '부속기기 명', '형식', '제작번호', '용량 및 규격', '제조처', '비고']
                        )
                        edited_accessory_df = st.data_editor(
                            accessory_df.rename(columns={
                                '순번': get_translation('col_seq'),
                                '부속기기 명': get_translation('col_accessory_name'),
                                '형식': get_translation('col_accessory_type'),
                                '제작번호': get_translation('col_accessory_serial'),
                                '용량 및 규격': get_translation('col_capacity_spec'),
                                '제조처': get_translation('col_maker'),
                                '비고': get_translation('col_notes')
                            }),
                            num_rows="dynamic",
                            width='stretch',
                            key="accessory_data_editor"
                        )
                        st.session_state.accessory_specs = edited_accessory_df.rename(columns={
                            get_translation('col_seq'): '순번',
                            get_translation('col_accessory_name'): '부속기기 명',
                            get_translation('col_accessory_type'): '형식',
                            get_translation('col_accessory_serial'): '제작번호',
                            get_translation('col_capacity_spec'): '용량 및 규격',
                            get_translation('col_maker'): '제조처',
                            get_translation('col_notes'): '비고'
                        }).to_dict('records')
                        for idx, spec in enumerate(st.session_state.accessory_specs):
                            spec['순번'] = idx + 1
                        if st.session_state.accessory_specs:
                            st.write(f"**현재 {len(st.session_state.accessory_specs)}개의 부속기기가 등록되어 있습니다.**")
                        
                        # 부속기기 관련 문서 업로드
                        uploaded_documents = st.file_uploader(
                            get_translation('upload_accessory_documents'),
                            type=['pdf', 'xlsx', 'xls'],  # 지원 파일 형식
                            accept_multiple_files=True,   # 여러 파일 업로드 가능
                            key="add_eq_accessory_documents"
                        )
                        if uploaded_documents:
                            for uploaded_file in uploaded_documents:
                                file_data = {
                                    'filename': uploaded_file.name,
                                    'file_type': uploaded_file.type,
                                    'content': uploaded_file.getvalue()  # 파일 바이너리 데이터
                                }
                                if file_data not in st.session_state.documents:  # 중복 방지
                                    st.session_state.documents.append(file_data)
                        
                        # 업로드된 문서 테이블 표시
                        documents_df = pd.DataFrame(
                            st.session_state.documents if st.session_state.documents else [],
                            columns=['파일명', '파일 유형', '다운로드']
                        )
                        for idx, doc in documents_df.iterrows():
                            if st.button("다운로드", key=f"download_doc_{idx}"):
                                st.download_button(
                                    label="다운로드",
                                    data=doc['content'],
                                    file_name=doc['filename'],
                                    mime=doc['file_type']
                                )
                        if st.session_state.documents:
                            st.write(f"**현재 {len(st.session_state.documents)}개의 문서가 등록되어 있습니다.**")
                    st.markdown("---")
            
                # SPARE PART 사양
                if fields_config.get('has_spare_part_specs', True):
                    with st.expander(get_translation('spare_part_specs'), expanded=False):
                        st.markdown(f"**{get_translation('add_row_instruction')}**")
                        spare_part_df = pd.DataFrame(
                            st.session_state.spare_part_specs if st.session_state.spare_part_specs else [],
                            columns=['SPARE PART', '교체 주기', '교체 일자']
                        )
                        edited_spare_part_df = st.data_editor(
                            spare_part_df.rename(columns={
                                'SPARE PART': get_translation('col_spare_part'),
                                '교체 주기': get_translation('col_maintenance_cycle'),
                                '교체 일자': get_translation('col_replacement_date')
                            }),
                            num_rows="dynamic",
                            column_config={
                                get_translation('col_replacement_date'): st.column_config.DateColumn(
                                    get_translation('col_replacement_date'),
                                    min_value=date(1950, 1, 1),
                                    format="YYYY-MM-DD"
                                )
                            },
                            width='stretch',
                            key="spare_part_data_editor"
                        )
                        st.session_state.spare_part_specs = edited_spare_part_df.rename(columns={
                            get_translation('col_spare_part'): 'SPARE PART',
                            get_translation('col_maintenance_cycle'): '교체 주기',
                            get_translation('col_replacement_date'): '교체 일자'
                        }).to_dict('records')
                        if st.session_state.spare_part_specs:
                            st.write(f"**현재 {len(st.session_state.spare_part_specs)}개의 SPARE PART가 등록되어 있습니다.**")
                    st.markdown("---")
            
                # 스크류 사양 (사출기만)
                if fields_config.get('has_screw_specs', False):
                    with st.expander(get_translation('screw_specs'), expanded=False):
                        st.markdown("###### 1) 재료 사양 기준")
                        col_h1, col_h2, col_h3 = st.columns([2, 2, 6])
                        with col_h1:
                            st.markdown("**스크류 규격**")
                        with col_h2:
                            st.markdown("**해당사항**")
                        with col_h3:
                            st.markdown("**재료 사양**")
                        col_data1, col_data2, col_data3 = st.columns([2, 2, 6])
                        with col_data1:
                            st.session_state.screw_specs['screw_type_general'] = st.text_input(
                                "일반 수지용 SCREW 규격",
                                value=st.session_state.screw_specs.get('screw_type_general', '일반 수지용 SCREW'),
                                key="screw_spec_general"
                            )
                        with col_data2:
                            st.session_state.screw_specs['applicable_general'] = st.text_input(
                                "일반 수지용 SCREW 해당사항",
                                value=st.session_state.screw_specs.get('applicable_general', ''),
                                key="applicable_general"
                            )
                        with col_data3:
                            st.session_state.screw_specs['material_spec_description'] = st.text_area(
                                "재료 사양 내용",
                                value=st.session_state.screw_specs.get('material_spec_description', ''),
                                key="material_spec_merged_content",
                                height=150
                            )
                        col_data4, col_data5, _ = st.columns([2, 2, 6])
                        with col_data4:
                            st.session_state.screw_specs['screw_type_wear'] = st.text_input(
                                "내마모성 SCREW 규격",
                                value=st.session_state.screw_specs.get('screw_type_wear', '내 마모성 SCREW'),
                                key="screw_spec_wear"
                            )
                        with col_data5:
                            st.session_state.screw_specs['applicable_wear'] = st.text_input(
                                "내마모성 SCREW 해당사항",
                                value=st.session_state.screw_specs.get('applicable_wear', ''),
                                key="applicable_wear"
                            )
                        st.markdown("---")
                    
                        st.markdown("###### 2) 일반용 SCREW")
                        st.session_state.screw_specs['general_cycle_df'] = st.data_editor(
                            pd.DataFrame(st.session_state.screw_specs.get('general_cycle', [])),
                            key="general_screw_cycle_editor",
                            hide_index=True,
                            num_rows="dynamic",
                            column_order=("해당 사양", "A", "B", "C", "D"),
                            column_config={
                                "해당 사양": st.column_config.TextColumn("해당 사양", disabled=False),
                                "A": st.column_config.NumberColumn("A", min_value=1, format="%d"),
                                "B": st.column_config.NumberColumn("B", min_value=1, format="%d"),
                                "C": st.column_config.NumberColumn("C", min_value=1, format="%d"),
                                "D": st.column_config.NumberColumn("D", min_value=1, format="%d"),
                            },
                            width='stretch'
                        )
                        st.session_state.screw_specs['general_cycle'] = st.session_state.screw_specs['general_cycle_df'].to_dict('records')
                    
                        st.markdown("###### 3) 내마모성 SCREW")
                        st.session_state.screw_specs['wear_resistant_cycle_df'] = st.data_editor(
                            pd.DataFrame(st.session_state.screw_specs.get('wear_resistant_cycle', [])),
                            key="wear_resistant_screw_cycle_editor",
                            hide_index=True,
                            num_rows="dynamic",
                            column_order=("해당 사양", "A", "B", "C", "D"),
                            column_config={
                                "해당 사양": st.column_config.TextColumn("해당 사양", disabled=False),
                                "A": st.column_config.NumberColumn("A", min_value=1, format="%d"),
                                "B": st.column_config.NumberColumn("B", min_value=1, format="%d"),
                                "C": st.column_config.NumberColumn("C", min_value=1, format="%d"),
                                "D": st.column_config.NumberColumn("D", min_value=1, format="%d"),
                            },
                            width='stretch'
                        )
                        st.session_state.screw_specs['wear_resistant_cycle'] = st.session_state.screw_specs['wear_resistant_cycle_df'].to_dict('records')
                    st.markdown("---")
            
                # 작동유 사양
                if fields_config.get('has_oil_specs', True):
                    with st.expander(get_translation('oil_specs'), expanded=False):
                        st.markdown(f"**{get_translation('add_row_instruction')}**")
                    
                        cols_tables_and_note = st.columns([7, 3])
                    
                        with cols_tables_and_note[0]:
                            oil_df = pd.DataFrame(
                                st.session_state.oil_specs if st.session_state.oil_specs else [],
                                columns=['구분', '적용 작동유 SPCE', '교체 주기']
                            )
                            edited_oil_df = st.data_editor(
                                oil_df.rename(columns={
                                    '구분': get_translation('col_category'),
                                    '적용 작동유 SPCE': get_translation('col_applicable_oil'),
                                    '교체 주기': get_translation('col_maintenance_cycle')
                                }),
                                num_rows="dynamic",
                                width='stretch',
                                key="oil_data_editor"
                            )
                            st.session_state.oil_specs = edited_oil_df.rename(columns={
                                get_translation('col_category'): '구분',
                                get_translation('col_applicable_oil'): '적용 작동유 SPCE',
                                get_translation('col_maintenance_cycle'): '교체 주기'
                            }).to_dict('records')
                            st.write(f"**현재 {len(st.session_state.oil_specs)}개의 작동유 항목이 등록되어 있습니다.**")
                    
                        with cols_tables_and_note[1]:
                            st.markdown("###### 작동유 점도 측정 방법")
                            note_text = """
* 작동유 점도 측정 방법
1. 육안검사
  각기 다른 용기에 담긴 시료와 새 오일의 색상,투명도,이물질 등을 비교 평가한다
2. 낙적검사
  여과지에 시료를 몇방울 떨어뜨려 2-3시간후 관찰하여 얼룩여부 확인 --얼룩 없을시 합격처리함
"""
                            st.markdown(note_text)
                    st.markdown("---")
            
                # ========== 동적으로 추가된 커스텀 섹션들 ==========
                # 기본 섹션 목록
                default_sections = ['has_accessory_specs', 'has_spare_part_specs', 'has_screw_specs', 'has_oil_specs']
            
                # fields_config에서 커스텀 섹션 찾기
                for config_key, config_value in fields_config.items():
                    if config_key.startswith('has_') and config_value == True and config_key not in default_sections:
                        section_key = config_key.replace('has_', '')  # 먼저 section_key 계산
        
                        # field_definitions에서 라벨 찾기 (prefix 제거 후 매칭)
                        all_fields = get_field_definitions()
                        field_def = next((f for f in all_fields if f['field_key'] == section_key), None)
        
                        if field_def:
                            field_label = field_def['field_label']
            
                            with st.expander(f"{field_label}", expanded=False):
                                custom_section_value = st.text_area(
                                    f"{field_label} 내용 입력",
                                    value=st.session_state.custom_sections.get(section_key, ''),
                                    key=f"add_custom_section_{section_key}",
                                    height=150,
                                    help=f"{field_label}에 대한 정보를 입력하세요"
                                )
                                st.session_state.custom_sections[section_key] = custom_section_value
                            st.markdown("---")
                        else:
                            # 필드 정의가 없을 때 경고 (옵션: 사용자에게 피드백)
                            st.warning(f"커스텀 섹션 '{section_key}'의 정의를 찾을 수 없습니다. 관리자에서 확인하세요.")
            
                # 기타사항 및 이미지 업로드
                st.session_state.other_notes = st.text_area(get_translation('other_notes'), value=st.session_state.get('other_notes', ''), key="add_other_notes")
                uploaded_images = st.file_uploader(get_translation('upload_image'), type=['png', 'jpg', 'jpeg'], accept_multiple_files=True, key="add_eq_images")
            
                if fields_config.get('has_oil_specs', True):
                    st.markdown("**1년 경과 후 사후관리 방안:**")
                    st.markdown("*아래에 내용을 작성하세요. 줄바꿈이 자동으로 적용됩니다.*")
                    st.session_state.oil_aftercare = st.text_area("사후관리 내용", value=st.session_state.get('oil_aftercare', ''), key="add_oil_aftercare", height=100, label_visibility="collapsed")
            
                # 설비 추가 최종 제출 버튼
                if st.form_submit_button(get_translation('add_equipment_button'), type="primary"):
                    image_urls_str = upload_images(uploaded_images) if uploaded_images else ""
                
                    if factory_id and name and model:
                        # 문서 업로드 (부속기기 관련 문서만 처리)
                        document_urls = []
                        if uploaded_documents:
                            for doc in uploaded_documents:
                                url = upload_document_to_supabase(doc)
                                if url:
                                    document_urls.append(url)
                        
                        # details_dict 구성 (공통 필드 + 특화 필드 + 커스텀 섹션)
                        details_dict = {
                            'product_name': product_name,
                            'maker': maker,
                            'serial_number': serial_number,
                            'production_date': str(production_date) if production_date else None,
                            'acquisition_cost': acquisition_cost,
                            'acquisition_date': str(acquisition_date) if acquisition_date else None,
                            'acquisition_basis': acquisition_basis,
                            'purchase_date': str(purchase_date) if purchase_date else None,
                            'installation_location': installation_location,
                            'motor_capacity': motor_capacity,
                            'heater_capacity': heater_capacity,
                            'total_weight': total_weight,
                            'other_notes': st.session_state.other_notes,
                            'fields_config': fields_config,  # fields_config 추가
                            'document_urls': ','.join(document_urls) if document_urls else '',  # 문서 URL 추가
                            **specific_fields_data,  # 특화 필드
                            **st.session_state.custom_sections  # 커스텀 섹션
                        }
                    
                        # 스크류 사양 (있을 경우만)
                        screw_specs_to_add = None
                        if fields_config.get('has_screw_specs', False):
                            screw_specs_to_add = {
                                'material_spec_description': st.session_state.screw_specs.get('material_spec_description', ''),
                                'screw_type_general': st.session_state.screw_specs.get('screw_type_general', ''),
                                'applicable_general': st.session_state.screw_specs.get('applicable_general', ''),
                                'screw_type_wear': st.session_state.screw_specs.get('screw_type_wear', ''),
                                'applicable_wear': st.session_state.screw_specs.get('applicable_wear', ''),
                                'general_cycle': st.session_state.screw_specs.get('general_cycle', []),
                                'wear_resistant_cycle': st.session_state.screw_specs.get('wear_resistant_cycle', [])
                            }
                    
                        # 작동유 사양 (있을 경우만)
                        oil_specs_to_add = []
                        if fields_config.get('has_oil_specs', True):
                            oil_specs_to_add = st.session_state.oil_specs + [
                                {'notes': '1년 경과 후 사후관리 방안'},
                                {'aftercare': st.session_state.oil_aftercare}
                            ]
                    
                        success, message = add_equipment(
                            factory_id=factory_id,
                            name=name,
                            model=model,
                            equipment_type=selected_template['name'],
                            details_dict=details_dict,
                            accessory_specs=st.session_state.accessory_specs if fields_config.get('has_accessory_specs', True) else [],
                            spare_part_specs=st.session_state.spare_part_specs if fields_config.get('has_spare_part_specs', True) else [],
                            documents=st.session_state.documents,
                            screw_specs=screw_specs_to_add,
                            oil_specs=oil_specs_to_add,
                            image_urls=image_urls_str
                        )
                    
                        if success:
                            reset_add_equipment_form_state()  # 기존 리셋 함수 (필요 시)
                            st.success("설비가 성공적으로 추가되었습니다. 입력 값이 유지됩니다. 초기화 버튼으로 리셋하세요.")
                            st.rerun()  # rerun으로 새로고침, 값 유지
                        else:
                            st.error(f"설비 추가 실패: {message}")
                    else:
                        st.error("필수 정보를 모두 입력해주세요: 설비명, 모델")
        else:
            st.info("👆 먼저 설비 종류를 선택해주세요.")

# ------------------------ 정비 이력 추가 ------------------------
    with tabs[2]:
        st.header(get_translation('add_maintenance_log'))
        equipment_list = get_equipment(factory_id)
        if not equipment_list:
            st.warning(get_translation('no_equipment_registered'))
        else:
            eq_options = {eq['name']: eq['id'] for eq in equipment_list}
            selected_eq_name = st.selectbox(get_translation('select_equipment'), options=list(eq_options.keys()), key='add_log_equipment_select')
            selected_eq_id = eq_options.get(selected_eq_name, None)

            if selected_eq_id:
                with st.form("add_log_form", clear_on_submit=True):
                    engineer = st.text_input(get_translation('engineer_name'))
                    action_category = st.selectbox(
                        get_translation('action_category'),
                        options=[
                            get_translation('electrical'),
                            get_translation('mechanical'),
                            get_translation('drive'),
                            get_translation('other_category')
                        ],
                        key='add_log_action_category'
                    )
                    action = st.text_input(get_translation('maintenance_action'))
                    notes = st.text_area(get_translation('notes'))
                    col_dt1, col_dt2 = st.columns(2)
                    with col_dt1:
                        maintenance_date = st.date_input(
                            get_translation('maintenance_date'),
                            value=date.today(),
                            min_value=date(1900, 1, 1)
                        )
                    with col_dt2:
                        maintenance_time = st.time_input(
                            get_translation('maintenance_time'),
                            value=time(datetime.now().hour, datetime.now().minute)
                        )
                    cost = st.number_input("정비 비용", min_value=0.0, format="%.2f", key="add_log_cost")
                    uploaded_images = st.file_uploader(
                        get_translation('upload_image'),
                        type=['png', 'jpg', 'jpeg'],
                        accept_multiple_files=True
                    )
                    submitted = st.form_submit_button(get_translation('add_log_button'))
                    if submitted:
                        image_urls = upload_images(uploaded_images) if uploaded_images else None
                        add_log(selected_eq_id, engineer, action, notes, maintenance_date, maintenance_time, image_urls, cost, action_category)
                        st.success("정비 이력이 성공적으로 추가되었습니다.")
                        st.rerun()

# ------------------------ 정비 이력 확인 ------------------------
    with tabs[3]:
        st.header(get_translation('view_maintenance_log'))
        equipment_list = get_equipment(factory_id)
        if not equipment_list:
            st.warning(get_translation('no_equipment_registered'))
        else:
            equipment_search = st.text_input("설비 검색", placeholder="설비 이름, 제조사, 모델로 검색...", key="view_log_eq_search")
            filtered_equipment = [eq for eq in equipment_list if equipment_search.lower() in eq['name'].lower() or equipment_search.lower() in eq.get('maker', '').lower() or equipment_search.lower() in eq.get('model', '').lower()] if equipment_search else equipment_list
            eq_options = {eq['name']: eq['id'] for eq in filtered_equipment}
            selected_eq_name_view = st.selectbox(get_translation('select_equipment'), options=list(eq_options.keys()), key='view_log_equipment_select')
            selected_eq_id_view = eq_options.get(selected_eq_name_view, None)

            if selected_eq_id_view:
                logs = get_maintenance_logs(equipment_id=selected_eq_id_view)
                if not logs:
                    st.info(get_translation('no_logs'))
                else:
                    logs_df = pd.DataFrame(logs)
                    logs_df['maintenance_date'] = pd.to_datetime(logs_df['maintenance_date']).dt.strftime('%Y-%m-%d %H:%M')
                    logs_df['equipment_name'] = logs_df['equipment'].apply(lambda x: x['name'])
                    logs_df = logs_df.rename(columns={
                        'maintenance_date': get_translation('maintenance_date'),
                        'engineer': get_translation('col_engineer'),
                        'action': get_translation('col_action'),
                        'notes': get_translation('col_notes'),
                        'image_urls': get_translation('col_image_urls'),
                        'id': get_translation('col_log_id'),
                        'cost': "정비 비용"
                    })

                    logs_df[get_translation('maintenance_date')] = logs_df[get_translation('maintenance_date')].fillna('')
                    logs_df[get_translation('col_engineer')] = logs_df[get_translation('col_engineer')].fillna('')
                    logs_df[get_translation('col_action')] = logs_df[get_translation('col_action')].fillna('')
                    logs_df[get_translation('col_notes')] = logs_df[get_translation('col_notes')].fillna('')
                    logs_df["정비 비용"] = logs_df["정비 비용"].fillna(0.0)

                    log_search = st.text_input("상세 이력 검색", placeholder="일자, 작업자, 내용으로 검색...", key="view_log_detail_search")
                    if log_search:
                        logs_df = logs_df[
                            logs_df[get_translation('maintenance_date')].str.contains(log_search, case=False, na=False) |
                            logs_df[get_translation('col_engineer')].str.contains(log_search, case=False, na=False) |
                            logs_df[get_translation('col_action')].str.contains(log_search, case=False, na=False) |
                            logs_df[get_translation('col_notes')].str.contains(log_search, case=False, na=False)
                        ]

                    if log_search and logs_df.empty:
                        st.warning("검색 조건에 맞는 이력이 없습니다.")
                    else:
                        st.dataframe(logs_df[[get_translation('maintenance_date'), get_translation('col_engineer'), get_translation('col_action'), get_translation('col_notes'), "정비 비용", get_translation('col_image_urls'), get_translation('col_log_id')]], width='stretch')

                    log_options = {f"날짜: {log['maintenance_date']}, 작업: {log['action']}": log['id'] for log in logs}
                    selected_log_id_view = st.selectbox(get_translation('view_detail_log'), options=[''] + list(log_options.keys()), key='view_detail_log_select')

                    if selected_log_id_view:
                        selected_log_id = log_options[selected_log_id_view]
                        selected_log_data = next((log for log in logs if log['id'] == selected_log_id), None)
                        if selected_log_data:
                            with st.expander(f"**{get_translation('log_details')}**", expanded=True):
                                st.write(f"**{get_translation('equipment_name')}:** {selected_log_data['equipment']['name']}")
                                st.write(f"**{get_translation('maintenance_date')}:** {selected_log_data['maintenance_date']}")
                                st.write(f"**{get_translation('engineer_name')}:** {selected_log_data['engineer']}")
                                st.write(f"**{get_translation('maintenance_action')}:** {selected_log_data['action']}")
                                st.write(f"**{get_translation('notes')}:** {selected_log_data['notes']}")
                                st.write(f"**정비 비용:** {selected_log_data.get('cost', 0.0)}")

                                if selected_log_data.get('image_urls'):
                                    st.subheader(get_translation('attachments'))
                                    image_urls = selected_log_data['image_urls'].split(',')
                                    cols = st.columns(min(len(image_urls), 3))
                                    for i, url in enumerate(image_urls):
                                        with cols[i % 3]:
                                            st.image(url.strip(), use_column_width='auto')
                                else:
                                    st.info(get_translation('no_attachments'))

                    if not logs_df.empty:
                        st.subheader("정비 비용 추이 분석")
                        logs_df['날짜'] = pd.to_datetime(logs_df[get_translation('maintenance_date')]).dt.date
                        cost_trend = logs_df.groupby('날짜')['정비 비용'].sum().reset_index()
                        cost_trend['날짜'] = pd.to_datetime(cost_trend['날짜'])
                        cost_trend = cost_trend.sort_values('날짜')
                        st.dataframe(cost_trend, width='stretch')

                        chart = alt.Chart(cost_trend).mark_line().encode(
                            x=alt.X('날짜:T', title=get_translation('maintenance_date')),
                            y=alt.Y('정비 비용:Q', title='정비 비용'),
                            tooltip=['날짜', '정비 비용']
                        ).properties(
                            width='container'
                        )
                        st.altair_chart(chart)
                    else:
                        st.info("분석할 정비 이력이 없습니다.")

# ------------------------ 상태 기록 ------------------------
    with tabs[4]:
        st.header(get_translation('record_status'))
        equipment_list = get_equipment(factory_id)
        if not equipment_list:
            st.warning(get_translation('no_equipment_registered'))
        else:
            eq_options = {eq['name']: eq['id'] for eq in equipment_list}
            selected_eq_name = st.selectbox(get_translation('select_equipment'), options=list(eq_options.keys()), key='record_status_equipment_select')
            selected_eq_id = eq_options.get(selected_eq_name, None)

            if selected_eq_id:
                with st.form("record_status_form", clear_on_submit=True):
                    status = st.radio(get_translation('change_status'), [get_translation('normal'), get_translation('faulty'), get_translation('sold')])
                    notes = st.text_area(get_translation('notes'))
                    col_dt1, col_dt2 = st.columns(2)
                    with col_dt1:
                        history_date = st.date_input(get_translation('maintenance_date'), value=date.today())
                    with col_dt2:
                        history_time = st.time_input(get_translation('maintenance_time'), value=time(datetime.now().hour, datetime.now().minute))
                    submitted = st.form_submit_button(get_translation('record_button'))
                    if submitted:
                        add_status_history(selected_eq_id, status, notes, history_date, history_time)
                        st.rerun()

            st.subheader(get_translation('recent_status_history'))
            status_history = get_status_history(factory_id)
            if not status_history:
                st.info(get_translation('no_status_history'))
            else:
                history_df = pd.DataFrame(status_history)
                history_df['created_at'] = pd.to_datetime(history_df['created_at']).dt.strftime('%Y-%m-%d %H:%M')
                history_df['equipment_name'] = history_df['equipment'].apply(
                    lambda x: x['name'] if isinstance(x, dict) and 'name' in x else 'Unknown'
                )
                history_df = history_df.rename(columns={
                    'id': get_translation('col_history_id'),
                    'created_at': get_translation('col_created_at'),
                    'status': get_translation('col_status'),
                    'notes': get_translation('col_notes'),
                    'equipment_name': get_translation('col_equipment_name')
                })
                st.dataframe(
                    history_df[[
                        get_translation('col_history_id'),
                        get_translation('col_created_at'),
                        get_translation('col_equipment_name'),
                        get_translation('col_status'),
                        get_translation('col_notes')
                    ]],
                    width='stretch',
                    hide_index=True
                )

# ------------------------ 관리자 모드 ------------------------
    with tabs[5]:
        st.header(get_translation('admin_mode'))
        if 'admin_authenticated' not in st.session_state:
            st.session_state.admin_authenticated = False

        if not st.session_state.admin_authenticated:
            with st.form("admin_login_form"):
                admin_password = st.text_input(get_translation('admin_password'), type="password", key="admin_password_input")
                if st.form_submit_button(get_translation('login_button')):
                    if admin_password == ADMIN_PASSWORD:
                        st.session_state.admin_authenticated = True
                        st.success(get_translation('admin_login_success'))
                        st.rerun()
                    else:
                        st.error(get_translation('admin_login_fail'))
        else:
            admin_tabs = st.tabs([
                get_translation('add_factory'),
                get_translation('factory_update_delete'),
                get_translation('update_delete_equipment'),
                "⚙️ 설비 템플릿 관리",  # 새 탭
                get_translation('update_log_admin'),
                get_translation('update_status_admin')
            ])

            # 공장 추가
            with admin_tabs[0]:
                st.header(get_translation('add_factory'))
                with st.form("add_factory_form", clear_on_submit=True):
                    factory_name = st.text_input(get_translation('factory_name'), key="add_factory_name")
                    password = st.text_input(get_translation('password'), type="password", key="add_factory_password")
                    if st.form_submit_button(get_translation('add_factory_button')):
                        if factory_name and password:
                            add_factory(factory_name, password)
                            st.rerun()
                        else:
                            st.error("공장 이름과 비밀번호를 입력하세요.")

            # 공장 수정/삭제
            with admin_tabs[1]:
                st.header(get_translation('factory_update_delete'))
                factories_list = get_factories()
                factory_names = ['공장을 선택하세요'] + [f['name'] for f in factories_list]
                selected_factory_name = st.selectbox(
                    get_translation('select_factory_admin'),
                    options=factory_names,
                    key='selected_factory_name_admin_selectbox',
                    on_change=set_selected_factory
                )

                if st.session_state.selected_factory_id_admin:
                    factory_data = next((f for f in factories_list if f['id'] == st.session_state.selected_factory_id_admin), None)
                    if factory_data:
                        with st.form("update_factory_form"):
                            updated_factory_name = st.text_input(get_translation('factory_name'), value=factory_data['name'], key="update_factory_name")
                            updated_password = st.text_input(get_translation('password'), value=factory_data['password'], type="password", key="update_factory_password")
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button(get_translation('update_button')):
                                    update_factory(st.session_state.selected_factory_id_admin, updated_factory_name, updated_password)
                                    st.rerun()
                            with col2:
                                if st.form_submit_button(get_translation('delete_button')):
                                    delete_factory(st.session_state.selected_factory_id_admin)
                                    st.rerun()

            # 설비 수정/삭제 탭
            with admin_tabs[2]:
                st.header(get_translation('update_delete_equipment'))
                equipment_list = get_equipment()
                equipment_names = ['설비를 선택하세요'] + [eq['name'] for eq in equipment_list]
                selected_equipment_name = st.selectbox(
                    get_translation('select_equipment_admin'),
                    options=equipment_names,
                    key='selected_equipment_name_admin_selectbox',
                    on_change=set_selected_equipment
                )

                if st.session_state.selected_eq_id_admin:
                    eq_data = next((eq for eq in equipment_list if eq['id'] == st.session_state.selected_eq_id_admin), None)
                    if eq_data:

                        # 설비 ID 변경 감지 및 초기화
                        if 'last_selected_eq_id' not in st.session_state:
                            st.session_state.last_selected_eq_id = None
                        if st.session_state.last_selected_eq_id != st.session_state.selected_eq_id_admin:
                            if 'current_images_to_keep' in st.session_state:
                                del st.session_state.current_images_to_keep
                            st.session_state.last_selected_eq_id = st.session_state.selected_eq_id_admin

                        # 설비 타입 조회
                        equipment_type = eq_data.get('equipment_type', 'injection_molding')
                        templates = get_equipment_templates()
                        template_options = {t['name']: t['display_name'] for t in templates}
                        selected_equipment_type = st.selectbox(
                            "설비 종류",
                            options=list(template_options.keys()),
                            format_func=lambda x: template_options[x],
                            index=list(template_options.keys()).index(equipment_type) if equipment_type in template_options else 0,
                            key="update_equipment_type"
                        )

                        template = get_template_by_name(selected_equipment_type)

                        # 세션 상태 초기화 (작동유 관련)
                        if 'edit_oil_specs' not in st.session_state:
                            st.session_state.edit_oil_specs = eq_data.get('oil_specs', []) or [{'구분': '', '적용 작동유 SPCE': '', '교체 주기': ''}]
                        if 'edit_oil_notes' not in st.session_state:
                            st.session_state.edit_oil_notes = eq_data.get('oil_notes', '')
                        if 'edit_oil_aftercare' not in st.session_state:
                            st.session_state.edit_oil_aftercare = eq_data.get('oil_aftercare', '')
                        if 'edit_documents' not in st.session_state:
                            st.session_state.edit_documents = eq_data.get('documents', []) or []

                        # details에서 특화 필드 추출
                        details_json = eq_data.get('details', '{}')
                        if isinstance(details_json, str):
                            try:
                                extra_fields = json.loads(details_json)
                            except:
                                extra_fields = {}
                        else:
                            extra_fields = details_json if details_json else {}

                        with st.form("update_equipment_form"):

                            # 공통 필드
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                name = st.text_input(get_translation('equipment_name'), value=eq_data['name'], key="update_eq_name")
                            with col2:
                                product_name = st.text_input(get_translation('product_name'), value=eq_data.get('product_name', ''), key="update_eq_product_name")
                            with col3:
                                maker = st.text_input(get_translation('maker'), value=eq_data.get('maker', ''), key="update_eq_maker")

                            col4, col5, col6 = st.columns(3)
                            with col4:
                                model = st.text_input(get_translation('model'), value=eq_data['model'], key="update_eq_model")
                            with col5:
                                serial_number = st.text_input(get_translation('serial_number'), value=eq_data.get('serial_number', ''), key="update_eq_serial_number")
                            with col6:
                                production_date = st.date_input(
                                    get_translation('production_date'),
                                    value=get_date_value(eq_data.get('production_date', None)),
                                    key="update_eq_production_date"
                                )

                            col7, col8, col9 = st.columns(3)
                            with col7:
                                acquisition_cost = st.text_input(get_translation('acquisition_cost'), value=eq_data.get('acquisition_cost', ''), key="update_eq_acquisition_cost")
                            with col8:
                                acquisition_date = st.date_input(
                                    get_translation('acquisition_date'),
                                    value=get_date_value(eq_data.get('acquisition_date', None)),
                                    key="update_eq_acquisition_date"
                                )
                            with col9:
                                acquisition_basis = st.text_input(get_translation('acquisition_basis'), value=eq_data.get('acquisition_basis', ''), key="update_eq_acquisition_basis")

                            col10, col11, col12 = st.columns(3)
                            with col10:
                                purchase_date = st.date_input(
                                    get_translation('purchase_date'),
                                    value=get_date_value(eq_data.get('purchase_date', None)),
                                    key="update_eq_purchase_date"
                                )
                            with col11:
                                installation_location = st.text_input(get_translation('installation_location'), value=eq_data.get('installation_location', ''), key="update_eq_installation_location")
                            with col12:
                                equipment_grade = st.text_input(get_translation('equipment_grade'), value=eq_data.get('equipment_grade', ''), key="update_eq_equipment_grade")

                            col13, col14, col15 = st.columns(3)
                            with col13:
                                motor_capacity = st.text_input(get_translation('motor_capacity_specs'), value=eq_data.get('motor_capacity', ''), key="update_eq_motor_capacity")
                            with col14:
                                heater_capacity = st.text_input(get_translation('heater_capacity_specs'), value=eq_data.get('heater_capacity', ''), key="update_eq_heater_capacity")
                            with col15:
                                total_weight = st.text_input(get_translation('total_weight'), value=eq_data.get('total_weight', ''), key="update_eq_total_weight")

                            col16, col17, col18 = st.columns(3)
                            with col16:
                                status = st.radio(get_translation('status'), [get_translation('normal'), get_translation('faulty'), get_translation('sold')], index=0 if eq_data['status'] == '정상' else 1 if eq_data['status'] == '고장' else 2)
                            with col17:
                                st.empty()  # 빈 공간
                            with col18:
                                st.empty()  # 빈 공간

                            st.markdown("---")

                            # 특화 필드
                            if template:
                                fields_config = template.get('fields_config', {})
                                specific_fields = fields_config.get('specific_fields', [])
                                if specific_fields:
                                    st.markdown(f"##### {template['display_name']} 전용 사양")
                                    specific_fields_data = {}
                                    for i in range(0, len(specific_fields), 3):
                                        cols = st.columns(3)
                                        for j in range(3):
                                            idx = i + j
                                            if idx < len(specific_fields):
                                                field_key = specific_fields[idx]
                                                field_def = FIELD_DEFINITIONS.get(field_key, {'label': field_key, 'type': 'text'})
                                                with cols[j]:
                                                    translated_label = get_translation(field_def['label'])
                                                    if field_def['type'] == 'text':
                                                        specific_fields_data[field_key] = st.text_input(
                                                            translated_label,
                                                            value=extra_fields.get(field_key, ''),
                                                            key=f"update_spec_{field_key}"
                                                        )
                                                    elif field_def['type'] == 'number':
                                                        specific_fields_data[field_key] = st.number_input(
                                                            translated_label,
                                                            value=float(extra_fields.get(field_key, 0)) if extra_fields.get(field_key) else 0,
                                                            key=f"update_spec_{field_key}"
                                                        )
                                                    elif field_def['type'] == 'date':
                                                        specific_fields_data[field_key] = st.date_input(
                                                            translated_label,
                                                            value=get_date_value(extra_fields.get(field_key)),
                                                            key=f"update_spec_{field_key}"
                                                        )

                            st.markdown("---")

                            # 부속기기 사양
                            st.markdown(f"##### {get_translation('accessory_specs')}")
                            if len(st.session_state.edit_accessory_specs) > 0:
                                st.write(f"**현재 {len(st.session_state.edit_accessory_specs)}개의 부속기기가 등록되어 있습니다.**")
                                accessory_df = pd.DataFrame(st.session_state.edit_accessory_specs)
                                edited_accessory_df = st.data_editor(
                                    accessory_df.rename(columns={
                                        '순번': get_translation('col_seq'),
                                        '부속기기 명': get_translation('col_accessory_name'),
                                        '형식': get_translation('col_accessory_type'),
                                        '제작번호': get_translation('col_accessory_serial'),
                                        '용량 및 규격': get_translation('col_capacity_spec'),
                                        '제조처': get_translation('col_maker'),
                                        '비고': get_translation('col_notes')
                                    }),
                                    num_rows="dynamic",
                                    width='stretch'
                                )
                                st.session_state.edit_accessory_specs = edited_accessory_df.rename(columns={
                                    get_translation('col_seq'): '순번',
                                    get_translation('col_accessory_name'): '부속기기 명',
                                    get_translation('col_accessory_type'): '형식',
                                    get_translation('col_accessory_serial'): '제작번호',
                                    get_translation('col_capacity_spec'): '용량 및 규격',
                                    get_translation('col_maker'): '제조처',
                                    get_translation('col_notes'): '비고'
                                }).to_dict('records')

                            st.markdown("---")

                            # SPARE PART 사양
                            st.markdown(f"##### {get_translation('spare_part_specs')}")
                            if len(st.session_state.edit_spare_part_specs) > 0:
                                st.write(f"**현재 {len(st.session_state.edit_spare_part_specs)}개의 SPARE PART가 등록되어 있습니다.**")
                                spare_part_df = pd.DataFrame(st.session_state.edit_spare_part_specs)
                                edited_spare_part_df = st.data_editor(
                                    spare_part_df.rename(columns={
                                        'SPARE PART': get_translation('col_spare_part'),
                                        '교체 주기': get_translation('col_maintenance_cycle'),
                                        '교체 일자': get_translation('col_replacement_date')
                                    }),
                                    num_rows="dynamic",
                                    column_config={
                                        get_translation('col_replacement_date'): st.column_config.DateColumn(
                                            get_translation('col_replacement_date'),
                                            min_value=date(1950, 1, 1),
                                            format="YYYY-MM-DD"
                                        )
                                    },
                                    width='stretch'
                                )
                                st.session_state.edit_spare_part_specs = edited_spare_part_df.rename(columns={
                                    get_translation('col_spare_part'): 'SPARE PART',
                                    get_translation('col_maintenance_cycle'): '교체 주기',
                                    get_translation('col_replacement_date'): '교체 일자'
                                }).to_dict('records')

                            st.markdown("---")

                            # 문서
                            st.markdown(f"##### {get_translation('documents')}")
                            if len(st.session_state.edit_documents) > 0:
                                st.write(f"**현재 {len(st.session_state.edit_documents)}개의 문서가 등록되어 있습니다.**")
                                documents_df = pd.DataFrame(st.session_state.edit_documents)
                                edited_documents_df = st.data_editor(
                                    documents_df.rename(columns={
                                        '기술 자료명': get_translation('col_doc_name'),
                                        '취급 설명서': get_translation('col_manual'),
                                        '전기 도면': get_translation('col_electric_drawing'),
                                        '유.증압도면': get_translation('col_hydraulic_drawing'),
                                        '윤활 기준표': get_translation('col_lubrication_std'),
                                        'url': get_translation('col_url')  # URL 컬럼 추가
                                    }),
                                    num_rows="dynamic",
                                    width='stretch'
                                )
                                st.session_state.edit_documents = edited_documents_df.rename(columns={
                                    get_translation('col_doc_name'): '기술 자료명',
                                    get_translation('col_manual'): '취급 설명서',
                                    get_translation('col_electric_drawing'): '전기 도면',
                                    get_translation('col_hydraulic_drawing'): '유.증압도면',
                                    get_translation('col_lubrication_std'): '윤활 기준표',
                                    get_translation('col_url'): 'url'  # URL 컬럼 복원
                                }).to_dict('records')

                            # 문서 첨부
                            uploaded_documents = st.file_uploader(
                                get_translation('upload_documents'),
                                type=['pdf', 'xlsx', 'xls'],
                                accept_multiple_files=True,
                                key="update_eq_documents"
                            )
                            if uploaded_documents:
                                for uploaded_file in uploaded_documents:
                                    file_data = {
                                        '기술 자료명': uploaded_file.name,
                                        '취급 설명서': '',
                                        '전기 도면': '',
                                        '유.증압도면': '',
                                        '윤활 기준표': '',
                                        'url': upload_document_to_supabase(uploaded_file),  # 즉시 업로드 후 URL 저장
                                        'file_type': uploaded_file.type
                                    }
                                    if file_data['url'] and not any(d['기술 자료명'] == file_data['기술 자료명'] and d['url'] == file_data['url'] for d in st.session_state.edit_documents):
                                                st.session_state.edit_documents.append(file_data)
                            st.markdown("---")

                            # 스크류 사양 (사출기만)
                            if template and fields_config.get('has_screw_specs', False):
                                st.markdown(f"##### {get_translation('screw_specs')}")
                                st.markdown("###### 1) 재료 사양 기준")
                                col_h1, col_h2, col_h3 = st.columns([2, 2, 6])
                                with col_h1:
                                    st.markdown("**스크류 규격**")
                                with col_h2:
                                    st.markdown("**해당사항**")
                                with col_h3:
                                    st.markdown("**재료 사양**")
                                col_data1, col_data2, col_data3 = st.columns([2, 2, 6])
                                with col_data1:
                                    st.session_state.edit_screw_specs['screw_type_general'] = st.text_input(
                                        "일반 수지용 SCREW 규격",
                                        value=st.session_state.edit_screw_specs.get('screw_type_general', '일반 수지용 SCREW'),
                                        key="update_screw_spec_general"
                                    )
                                with col_data2:
                                    st.session_state.edit_screw_specs['applicable_general'] = st.text_input(
                                        "일반 수지용 SCREW 해당사항",
                                        value=st.session_state.edit_screw_specs.get('applicable_general', ''),
                                        key="update_applicable_general"
                                    )
                                with col_data3:
                                    st.session_state.edit_screw_specs['material_spec_description'] = st.text_area(
                                        "재료 사양 내용",
                                        value=st.session_state.edit_screw_specs.get('material_spec_description', ''),
                                        key="update_material_spec_merged_content",
                                        height=150
                                    )
                                col_data4, col_data5, _ = st.columns([2, 2, 6])
                                with col_data4:
                                    st.session_state.edit_screw_specs['screw_type_wear'] = st.text_input(
                                        "내마모성 SCREW 규격",
                                        value=st.session_state.edit_screw_specs.get('screw_type_wear', '내마모성 SCREW'),
                                        key="update_screw_spec_wear"
                                    )
                                with col_data5:
                                    st.session_state.edit_screw_specs['applicable_wear'] = st.text_input(
                                        "내마모성 SCREW 해당사항",
                                        value=st.session_state.edit_screw_specs.get('applicable_wear', ''),
                                        key="update_applicable_wear"
                                    )

                                st.markdown("---")
                                st.markdown("###### 2) 일반용 SCREW")
                                st.session_state.edit_screw_specs['general_cycle_df'] = st.data_editor(
                                    pd.DataFrame(st.session_state.edit_screw_specs.get('general_cycle', [{'해당 사양': '교체 주기 (월)', 'A': '5', 'B': '5', 'C': '3', 'D': '3'}])),
                                    key="update_general_screw_cycle_editor",
                                    hide_index=True,
                                    column_order=("해당 사양", "A", "B", "C", "D"),
                                    column_config={
                                        "해당 사양": st.column_config.TextColumn("해당 사양", disabled=True),
                                        "A": st.column_config.NumberColumn("A", min_value=1, format="%d"),
                                        "B": st.column_config.NumberColumn("B", min_value=1, format="%d"),
                                        "C": st.column_config.NumberColumn("C", min_value=1, format="%d"),
                                        "D": st.column_config.NumberColumn("D", min_value=1, format="%d"),
                                    },
                                    width='stretch'
                                )
                                st.markdown("###### 3) 내마모성 SCREW")
                                st.session_state.edit_screw_specs['wear_resistant_cycle_df'] = st.data_editor(
                                    pd.DataFrame(st.session_state.edit_screw_specs.get('wear_resistant_cycle', [{'해당 사양': '교체 주기 (월)', 'A': '10', 'B': '10', 'C': '5', 'D': '5'}])),
                                    key="update_wear_resistant_screw_cycle_editor",
                                    hide_index=True,
                                    column_order=("해당 사양", "A", "B", "C", "D"),
                                    column_config={
                                        "해당 사양": st.column_config.TextColumn("해당 사양", disabled=True),
                                        "A": st.column_config.NumberColumn("A", min_value=1, format="%d"),
                                        "B": st.column_config.NumberColumn("B", min_value=1, format="%d"),
                                        "C": st.column_config.NumberColumn("C", min_value=1, format="%d"),
                                        "D": st.column_config.NumberColumn("D", min_value=1, format="%d"),
                                    },
                                    width='stretch'
                                )
                                st.markdown("---")

                            # 작동유 사양 (강제 렌더링)
                            st.markdown(f"##### {get_translation('oil_specs')}")
                            if len(st.session_state.edit_oil_specs) > 0:
                                st.write(f"**현재 {len(st.session_state.edit_oil_specs)}개의 작동유 항목이 등록되어 있습니다.**")
                                oil_df = pd.DataFrame(st.session_state.edit_oil_specs)
                                edited_oil_df = st.data_editor(
                                    oil_df.rename(columns={
                                        '구분': get_translation('col_category'),
                                        '적용 작동유 SPCE': get_translation('col_applicable_oil'),
                                        '교체 주기': get_translation('col_maintenance_cycle')
                                    }),
                                    num_rows="dynamic",
                                    width='stretch'
                                )
                                st.session_state.edit_oil_specs = edited_oil_df.rename(columns={
                                    get_translation('col_category'): '구분',
                                    get_translation('col_applicable_oil'): '적용 작동유 SPCE',
                                    get_translation('col_maintenance_cycle'): '교체 주기'
                                }).to_dict('records')
                            else:
                                st.info("작동유 항목이 없습니다. 새 항목을 추가하세요.")
                                st.session_state.edit_oil_specs = [{'구분': '', '적용 작동유 SPCE': '', '교체 주기': ''}]
                                oil_df = pd.DataFrame(st.session_state.edit_oil_specs)
                                edited_oil_df = st.data_editor(
                                    oil_df.rename(columns={
                                        '구분': get_translation('col_category'),
                                        '적용 작동유 SPCE': get_translation('col_applicable_oil'),
                                        '교체 주기': get_translation('col_maintenance_cycle')
                                    }),
                                    num_rows="dynamic",
                                    width='stretch'
                                )
                                st.session_state.edit_oil_specs = edited_oil_df.rename(columns={
                                    get_translation('col_category'): '구분',
                                    get_translation('col_applicable_oil'): '적용 작동유 SPCE',
                                    get_translation('col_maintenance_cycle'): '교체 주기'
                                }).to_dict('records')

                            st.session_state.edit_oil_notes = st.text_area(
                                "작동유 점도 측정 방법",
                                value=st.session_state.edit_oil_notes,
                                key="update_oil_notes",
                                height=100
                            )
                            st.markdown("**1년 경과 후 사후관리 방안:**")
                            st.markdown("*아래에 내용을 작성하세요. 줄바꿈이 자동으로 적용됩니다.*")
                            st.session_state.edit_oil_aftercare = st.text_area(
                                "사후관리 내용",
                                value=st.session_state.edit_oil_aftercare,
                                key="update_oil_aftercare",
                                height=100,
                                label_visibility="collapsed"
                            )
                            st.markdown("---")

                            # 기타사항
                            st.session_state.edit_other_notes = st.text_area(
                                get_translation('other_notes'),
                                value=eq_data.get('other_notes', ''),
                                key="update_other_notes"
                            )

                            # 이미지 처리 (use_column_width 제거)
                            current_image_urls = eq_data.get('image_urls', '')
                            if current_image_urls:
                                st.subheader("현재 등록된 이미지")
                                image_urls = [url.strip() for url in current_image_urls.split(',') if url.strip()]
                                if image_urls:
                                    num_cols = min(len(image_urls), 3)
                                    cols = st.columns(num_cols)
                                    images_to_keep = []
                                    for i, url in enumerate(image_urls):
                                        try:
                                            with cols[i % num_cols]:
                                                st.markdown(f'<img src="{url}" style="width:100%; height:auto;">', unsafe_allow_html=True)
                                                keep_image = st.checkbox("유지", value=True, key=f"keep_image_{i}")
                                                if keep_image:
                                                    images_to_keep.append(url)
                                        except Exception as e:
                                            st.warning(f"이미지 로드 실패 ({url}): {e}")
                                    st.session_state.current_images_to_keep = images_to_keep
                                else:
                                    st.info("등록된 이미지가 없습니다.")
                            else:
                                st.info("등록된 이미지가 없습니다.")

                            uploaded_images = st.file_uploader(
                                get_translation('upload_image'),
                                type=['png', 'jpg', 'jpeg'],
                                accept_multiple_files=True,
                                key="update_eq_images"
                            )

                            # 제출 및 삭제 버튼
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button(get_translation('update_button'), type="primary"):
                                    details_dict = {
                                        'product_name': product_name,
                                        'maker': maker,
                                        'serial_number': serial_number,
                                        'production_date': production_date.isoformat() if production_date else None,
                                        'acquisition_cost': acquisition_cost,
                                        'acquisition_date': acquisition_date.isoformat() if acquisition_date else None,
                                        'acquisition_basis': acquisition_basis,
                                        'purchase_date': purchase_date.isoformat() if purchase_date else None,
                                        'installation_location': installation_location,
                                        'equipment_grade': equipment_grade,
                                        'motor_capacity': motor_capacity,
                                        'heater_capacity': heater_capacity,
                                        'total_weight': total_weight,
                                        'other_notes': st.session_state.edit_other_notes,
                                        **specific_fields_data
                                    }

                                    screw_specs_to_update = None
                                    if template and fields_config.get('has_screw_specs', False):
                                        screw_specs_to_update = {
                                            'material_spec_description': st.session_state.edit_screw_specs.get('material_spec_description', ''),
                                            'screw_type_general': st.session_state.edit_screw_specs.get('screw_type_general', ''),
                                            'applicable_general': st.session_state.edit_screw_specs.get('applicable_general', ''),
                                            'screw_type_wear': st.session_state.edit_screw_specs.get('screw_type_wear', ''),
                                            'applicable_wear': st.session_state.edit_screw_specs.get('applicable_wear', ''),
                                            'general_cycle': st.session_state.edit_screw_specs['general_cycle_df'].to_dict('records'),
                                            'wear_resistant_cycle': st.session_state.edit_screw_specs['wear_resistant_cycle_df'].to_dict('records')
                                        }

                                    final_image_urls = st.session_state.get('current_images_to_keep', [])
                                    if uploaded_images:
                                        new_image_urls = upload_images(uploaded_images)
                                        if new_image_urls:
                                            final_image_urls.extend([url.strip() for url in new_image_urls.split(',') if url.strip()])

                                    success, message = update_equipment(
                                        equipment_id=st.session_state.selected_eq_id_admin,
                                        name=name,
                                        product_name=product_name,
                                        maker=maker,
                                        model=model,
                                        details_dict=details_dict,
                                        accessory_specs=st.session_state.edit_accessory_specs,
                                        spare_part_specs=st.session_state.edit_spare_part_specs,
                                        documents=st.session_state.edit_documents,
                                        screw_specs=screw_specs_to_update,
                                        oil_specs=st.session_state.edit_oil_specs,
                                        status=status,
                                        uploaded_images=uploaded_images,
                                        uploaded_documents=uploaded_documents,
                                        oil_notes=st.session_state.edit_oil_notes,
                                        oil_aftercare=st.session_state.edit_oil_aftercare
                                    )
                                    if success:
                                        st.session_state.edit_other_notes = ''
                                        if 'current_images_to_keep' in st.session_state:
                                            del st.session_state.current_images_to_keep
                                        st.success("설비 정보가 성공적으로 업데이트되었습니다.")
                                        st.rerun()
                                    else:
                                        st.error(f"설비 업데이트 실패: {message}")
                            with col2:
                                if st.form_submit_button(get_translation('delete_button'), type="primary"):
                                    delete_equipment(st.session_state.selected_eq_id_admin)
                                    st.session_state.edit_other_notes = ''
                                    st.success("설비가 성공적으로 삭제되었습니다.")
                                    st.rerun()

            # 설비 템플릿 관리 탭
            with admin_tabs[3]:
                st.header("⚙️ 설비 템플릿 관리")
    
                # 서브 탭 추가: 템플릿 관리 / 필드 관리
                template_subtabs = st.tabs(["📝 템플릿 관리", "🔧 필드 관리"])
    
                # === 템플릿 관리 탭 ===
                with template_subtabs[0]:
                    templates = get_equipment_templates()
        
                    st.subheader("📋 등록된 설비 템플릿")
                    if templates:
                        for template in templates:
                            tid = template['id']
                            with st.expander(f"🔧 {template['display_name']} ({template['name']})"):
                                st.json(template['fields_config'])
                    
                                col1, col2 = st.columns([3, 1])
                                with col2:
                                    if st.button("수정", key=f"edit_template_{tid}"):
                                        st.session_state[f"editing_template_{tid}"] = True
                        
                                    if st.button("삭제", key=f"delete_template_{tid}"):
                                        st.session_state[f"pending_delete_{tid}"] = True
                        
                                    if st.session_state.get(f"pending_delete_{tid}", False):
                                        st.warning(f"템플릿을 삭제하시겠습니까?")
                                        c1, c2 = st.columns([1, 1])
                                        with c1:
                                            if st.button("✅ 삭제", key=f"confirm_delete_{tid}"):
                                                success, message = delete_equipment_template(tid)
                                                st.session_state[f"pending_delete_{tid}"] = False
                                                if success:
                                                    st.success(message)
                                                    st.rerun()
                                                else:
                                                    st.error(message)
                                        with c2:
                                            if st.button("❌ 취소", key=f"cancel_delete_{tid}"):
                                                st.session_state[f"pending_delete_{tid}"] = False
                        
                                # 템플릿 수정 모드
                                if st.session_state.get(f"editing_template_{tid}", False):
                                    with st.form(f"update_template_form_{tid}"):
                                        col1, col2 = st.columns(2)
                                        with col1:
                                            update_template_name = st.text_input(
                                                "템플릿 이름 (영문, 소문자, 언더스코어만)",
                                                value=template['name'],
                                                key=f"update_template_name_{tid}"
                                            )
                                        with col2:
                                            update_template_display = st.text_input(
                                                "표시 이름 (한글)",
                                                value=template['display_name'],
                                                key=f"update_template_display_{tid}"
                                            )
                    
                                        st.markdown("##### 특화 필드 선택")
                                        st.info("💡 공통 필드는 자동으로 포함됩니다.")
                    
                                        # DB에서 동적으로 필드 로드
                                        all_fields = get_field_definitions()
                                        specific_fields = [f for f in all_fields if f['category'] == 'specific']
                    
                                        selected_fields = template['fields_config'].get('specific_fields', [])
                                        cols = st.columns(4)
                                        for idx, field in enumerate(specific_fields):
                                            with cols[idx % 4]:
                                                is_selected = field['field_key'] in selected_fields
                                                if st.checkbox(field['field_label'], value=is_selected, key=f"update_field_{field['field_key']}_{tid}"):
                                                    if field['field_key'] not in selected_fields:
                                                        selected_fields.append(field['field_key'])
                                                else:
                                                    if field['field_key'] in selected_fields:
                                                        selected_fields.remove(field['field_key'])
                    
                                        st.markdown("##### 선택적 섹션")
                                        section_fields = [f for f in all_fields if f['category'] == 'section']
                                        section_selections = {}
                                        cols = st.columns(4)
                                        for idx, section in enumerate(section_fields):
                                            with cols[idx % 4]:
                                                # has_ 접두사 처리
                                                config_key = section['field_key']
                                                if not config_key.startswith('has_'):
                                                    config_key = f"has_{config_key}"
                                                default_value = template['fields_config'].get(config_key, section['field_key'] not in ['screw_specs'])
                                                section_selections[config_key] = st.checkbox(
                                                    section['field_label'],
                                                    value=default_value,
                                                    key=f"update_section_{section['field_key']}_{tid}"
                                                )
                    
                                        if st.form_submit_button("템플릿 업데이트", type="primary"):
                                            if update_template_name and update_template_display:
                                                fields_config = {
                                                    'specific_fields': selected_fields,
                                                    **section_selections
                                                }
                                                success, message = update_equipment_template(
                                                    tid,
                                                    update_template_name,
                                                    update_template_display,
                                                    fields_config
                                                )
                                                if success:
                                                    st.session_state[f"editing_template_{tid}"] = False
                                                    st.success(message)
                                                    st.cache_data.clear()
                                                    st.rerun()
                                                else:
                                                    st.error(f"템플릿 업데이트 실패: {message}")
                                            else:
                                                st.error("템플릿 이름과 표시 이름을 모두 입력해주세요.")
        
                    st.markdown("---")
        
                    # 새 템플릿 추가 (동적 필드 사용)
                    st.subheader("➕ 새 설비 템플릿 추가")
        
                    with st.form("add_template_form"):
                        col1, col2 = st.columns(2)
                        with col1:
                            new_template_name = st.text_input(
                                "템플릿 이름 (영문, 소문자, 언더스코어만)",
                                placeholder="예: laser_cutting"
                            )
                        with col2:
                            new_template_display = st.text_input(
                                "표시 이름 (한글)",
                                placeholder="예: 레이저 커팅기"
                            )
            
                        st.markdown("##### 특화 필드 선택")
                        st.info("💡 공통 필드는 자동으로 포함됩니다.")
            
                        # DB에서 동적으로 필드 로드
                        all_fields = get_field_definitions()
                        specific_fields = [f for f in all_fields if f['category'] == 'specific']
                        selected_fields = []
                        cols = st.columns(4)
                        for idx, field in enumerate(specific_fields):
                            with cols[idx % 4]:
                                if st.checkbox(field['field_label'], key=f"new_field_{field['field_key']}"):
                                    selected_fields.append(field['field_key'])
            
                        st.markdown("##### 선택적 섹션")
                        section_fields = [f for f in all_fields if f['category'] == 'section']
                        section_selections = {}
                        cols = st.columns(4)
                        for idx, section in enumerate(section_fields):
                            with cols[idx % 4]:
                                # 기본값 설정
                                default_value = section['field_key'] not in ['screw_specs']  # screw만 false
        
                                # has_ 접두사가 없으면 추가
                                config_key = section['field_key']
                                if not config_key.startswith('has_'):
                                    config_key = f"has_{config_key}"
        
                                section_selections[config_key] = st.checkbox(
                                    section['field_label'],
                                    value=default_value,
                                    key=f"new_section_{section['field_key']}"
                                )

                        if st.form_submit_button("템플릿 추가", type="primary"):
                            if new_template_name and new_template_display:
                                fields_config = {
                                    'specific_fields': selected_fields,
                                    **section_selections  # 이미 has_ 접두사 포함됨
                                }
                    
                                success, message = add_equipment_template(
                                    new_template_name,
                                    new_template_display,
                                    fields_config
                                )
                    
                                if success:
                                    st.success(message)
                                    st.cache_data.clear()  # 캐시 초기화
                                    st.rerun()
                                else:
                                    st.error(f"템플릿 추가 실패: {message}")
                            else:
                                st.error("템플릿 이름과 표시 이름을 모두 입력해주세요.")
    
                # === 필드 관리 탭 ===
                with template_subtabs[1]:
                    st.subheader("🔧 필드 정의 관리")
        
                    all_fields = get_field_definitions()
        
                    # 기존 필드 목록
                    st.markdown("##### 📋 등록된 필드")
        
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**특화 필드**")
                        specific = [f for f in all_fields if f['category'] == 'specific']
                        for field in specific:
                            cols = st.columns([3, 1])
                            with cols[0]:
                                st.text(f"{field['field_label']} ({field['field_key']})")
                            with cols[1]:
                                if st.button("🗑️", key=f"del_field_{field['id']}"):
                                    success, msg = delete_field_definition(field['id'])
                                    if success:
                                        st.success(msg)
                                        st.cache_data.clear()
                                        st.rerun()
                                    else:
                                        st.error(msg)
        
                    with col2:
                        st.markdown("**선택적 섹션**")
                        sections = [f for f in all_fields if f['category'] == 'section']
                        for field in sections:
                            cols = st.columns([3, 1])
                            with cols[0]:
                                st.text(f"{field['field_label']} ({field['field_key']})")
                            with cols[1]:
                                if st.button("🗑️", key=f"del_section_{field['id']}"):
                                    success, msg = delete_field_definition(field['id'])
                                    if success:
                                        st.success(msg)
                                        st.cache_data.clear()
                                        st.rerun()
                                    else:
                                        st.error(msg)
        
                    st.markdown("---")
        
                    # 새 필드 추가
                    st.markdown("##### ➕ 새 필드 추가")
        
                    with st.form("add_field_form"):
                        col1, col2 = st.columns(2)
                        with col1:
                            new_field_key = st.text_input(
                                "필드 키 (영문, 소문자, 언더스코어만)",
                                placeholder="예: laser_power"
                            )
                            new_field_label = st.text_input(
                                "필드 표시명 (한글)",
                                placeholder="예: 레이저 출력"
                            )
                        with col2:
                            new_field_type = st.selectbox(
                                "필드 타입",
                                options=['text', 'number', 'date'],
                                index=0
                            )
                            new_field_category = st.selectbox(
                                "카테고리",
                                options=['specific', 'section'],
                                format_func=lambda x: '특화 필드' if x == 'specific' else '선택적 섹션'
                            )
            
                        if st.form_submit_button("필드 추가", type="primary"):
                            if new_field_key and new_field_label:
                                success, message = add_field_definition(
                                    new_field_key,
                                    new_field_label,
                                    new_field_type,
                                    new_field_category
                                )
                    
                                if success:
                                    st.success(message)
                                    st.cache_data.clear()  # 캐시 초기화
                                    st.rerun()
                                else:
                                    st.error(f"필드 추가 실패: {message}")
                            else:
                                st.error("필드 키와 표시명을 모두 입력해주세요.")

                        # 정비 이력 수정/삭제
                        with admin_tabs[4]:
                            st.header(get_translation('update_log_admin'))
                            equipment_list = get_equipment(factory_id)
                            if not equipment_list:
                                st.warning(get_translation('no_equipment_registered'))
                            else:
                                eq_options = {eq['name']: eq['id'] for eq in equipment_list}
                                selected_eq_name = st.selectbox(get_translation('select_equipment'), options=list(eq_options.keys()), key='admin_log_equipment_select')
                                selected_eq_id = eq_options.get(selected_eq_name, None)

                                # 설비 선택 변경 시 세션 초기화
                                if selected_eq_name != st.session_state.get('last_selected_log_eq_name'):
                                    st.session_state.last_selected_log_eq_name = selected_eq_name
                                    st.session_state.admin_log_select = None
                                    st.cache_data.clear()
                                    st.rerun()

                                if selected_eq_id:
                                    logs_list = get_maintenance_logs(equipment_id=selected_eq_id)
                                    st.info(f"설비 {selected_eq_name}의 정비 이력: {len(logs_list)}개")
                                    if not logs_list:
                                        st.warning(get_translation('no_logs'))
                                    else:
                                        log_options = {f"ID: {log['id']} | 날짜: {log['maintenance_date']} | 작업: {log['action']}": log['id'] for log in logs_list}
                                        selected_log_id_admin = st.selectbox(get_translation('select_log_admin'), options=list(log_options.keys()), key='admin_log_select')
                                        selected_log_id = log_options.get(selected_log_id_admin, None)

                                        if selected_log_id:
                                            log_data = next((log for log in logs_list if log['id'] == selected_log_id), None)
                                            if log_data:
                                                with st.form("update_log_form"):
                                                    engineer = st.text_input(get_translation('col_engineer'), value=log_data['engineer'])
                                                    action_category = st.selectbox(
                                                        get_translation('action_category'),
                                                        options=[
                                                            get_translation('electrical'),
                                                            get_translation('mechanical'),
                                                            get_translation('drive'),
                                                            get_translation('other_category')
                                                        ],
                                                        index=[
                                                            get_translation('electrical'),
                                                            get_translation('mechanical'),
                                                            get_translation('drive'),
                                                            get_translation('other_category')
                                                        ].index(log_data['action_category']) if log_data['action_category'] else 3,
                                                        key='update_log_action_category'
                                                    )
                                                    action = st.text_input(get_translation('col_action'), value=log_data['action'])
                                                    notes = st.text_area(get_translation('col_notes'), value=log_data['notes'])
                                                    uploaded_images = st.file_uploader(get_translation('upload_image'), type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
                                                    col1, col2 = st.columns(2)
                                                    with col1:
                                                        if st.form_submit_button(get_translation('update_button')):
                                                            update_log(selected_log_id, engineer, action, notes, uploaded_images, action_category)
                                                            st.rerun()
                                                    with col2:
                                                        if st.form_submit_button(get_translation('delete_button')):
                                                            delete_log(selected_log_id)
                                                            st.rerun()

            # 상태 기록 수정/삭제
            with admin_tabs[5]:
                st.header(get_translation('update_status_admin'))
                equipment_list = get_equipment(factory_id)
                if not equipment_list:
                    st.warning(get_translation('no_equipment_registered'))
                else:
                    eq_options = {eq['name']: eq['id'] for eq in equipment_list}
                    selected_eq_name = st.selectbox(get_translation('select_equipment'), options=list(eq_options.keys()), key='admin_status_equipment_select')
                    selected_eq_id = eq_options.get(selected_eq_name, None)

                    # 설비 선택 변경 시 세션 초기화
                    if selected_eq_name != st.session_state.get('last_selected_status_eq_name'):
                        st.session_state.last_selected_status_eq_name = selected_eq_name
                        st.session_state.admin_status_select = None
                        st.cache_data.clear()
                        st.rerun()

                    if selected_eq_id:
                        status_history = get_status_history(equipment_id=selected_eq_id)
                        st.info(f"설비 {selected_eq_name}의 상태 기록: {len(status_history)}개")
                        if not status_history:
                            st.warning(get_translation('no_status_history'))
                        else:
                            status_options = {f"ID: {h['id']} | 날짜: {h['created_at']} | 상태: {h['status']}": h['id'] for h in status_history}
                            selected_status_id_admin = st.selectbox(get_translation('select_status_admin'), options=list(status_options.keys()), key='admin_status_select')
                            selected_status_id = status_options.get(selected_status_id_admin, None)

                            if selected_status_id:
                                status_data = next((h for h in status_history if h['id'] == selected_status_id), None)
                                if status_data:
                                    with st.form("update_status_form"):
                                        status = st.radio(get_translation('status'), [get_translation('normal'), get_translation('faulty'), get_translation('sold')], index=0 if status_data['status'] == get_translation('normal') else 1 if status_data['status'] == get_translation('faulty') else 2)
                                        notes = st.text_area(get_translation('notes'), value=status_data['notes'])
                                        col1, col2 = st.columns(2)
                                        with col1:
                                            if st.form_submit_button(get_translation('update_button')):
                                                update_status_history(selected_status_id, status, notes)
                                                st.rerun()
                                        with col2:
                                            if st.form_submit_button(get_translation('delete_button')):
                                                delete_status_history(selected_status_id)
                                                st.rerun()
                                else:
                                    st.warning("선택한 상태 기록 데이터를 찾을 수 없습니다.")
