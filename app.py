import streamlit as st
import altair as alt
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import pandas as pd
import uuid
from datetime import datetime, date, time
import json

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
        {"구분": "작동유", "적용 작동유 SPCE": "LG 정유 SPCE, 쉘 란도 HD 46", "교체 주기": "9000HR / 1년"}
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
    query = supabase.from_('maintenance_logs').select('*, equipment(name, factories(name))').order('maintenance_date', desc=True)
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

def add_equipment(factory_id, name, model, details_dict, accessory_specs, spare_part_specs, documents, screw_specs, oil_specs, image_urls=None):
    try:
        for part in spare_part_specs:
            if isinstance(part.get('교체 일자'), date):
                part['교체 일자'] = part['교체 일자'].isoformat()

        for key, value in details_dict.items():
            if isinstance(value, date):
                details_dict[key] = value.isoformat() if value else None

        # screw_specs 처리
        if not isinstance(screw_specs, dict):
            screw_specs = {}
        else:
            if 'general_cycle_df' in screw_specs and isinstance(screw_specs['general_cycle_df'], pd.DataFrame):
                screw_specs['general_cycle'] = screw_specs['general_cycle_df'].to_dict('records')
                del screw_specs['general_cycle_df']
            if 'wear_resistant_cycle_df' in screw_specs and isinstance(screw_specs['wear_resistant_cycle_df'], pd.DataFrame):
                screw_specs['wear_resistant_cycle'] = screw_specs['wear_resistant_cycle_df'].to_dict('records')
                del screw_specs['wear_resistant_cycle_df']

        data = {
            "factory_id": factory_id,
            "name": name,
            "model": model,
            "status": '정상',
            **details_dict,
            "accessory_specs": json.dumps(accessory_specs, ensure_ascii=False),
            "spare_part_specs": json.dumps(spare_part_specs, ensure_ascii=False),
            "documents": json.dumps(documents, ensure_ascii=False),
            "screw_specs": json.dumps(screw_specs, ensure_ascii=False),
            "oil_specs": json.dumps(oil_specs, ensure_ascii=False),
            "image_urls": image_urls
        }

        supabase.from_('equipment').insert(data).execute()
        st.success("설비가 성공적으로 추가되었습니다.")
        st.cache_data.clear()
        return True, "설비가 성공적으로 추가되었습니다."
    except Exception as e:
        st.error(f"설비 추가 실패: {e}")
        return False, f"설비 추가 실패: {e}"

def update_equipment(equipment_id, name, product_name, maker, model, details_dict, accessory_specs, spare_part_specs, documents, screw_specs, oil_specs, status, uploaded_images, oil_notes='', oil_aftercare=''):
    try:
        new_image_urls = None
        if uploaded_images:
            new_image_urls = update_equipment_images(equipment_id, uploaded_images)

        for part in spare_part_specs:
            if isinstance(part.get('교체 일자'), date):
                part['교체 일자'] = part['교체 일자'].isoformat()

        for key, value in details_dict.items():
            if isinstance(value, date):
                details_dict[key] = value.isoformat() if value else None

        # screw_specs 처리
        if not isinstance(screw_specs, dict):
            screw_specs = {}
        else:
            if 'general_cycle_df' in screw_specs and isinstance(screw_specs['general_cycle_df'], pd.DataFrame):
                screw_specs['general_cycle'] = screw_specs['general_cycle_df'].to_dict('records')
                del screw_specs['general_cycle_df']
            if 'wear_resistant_cycle_df' in screw_specs and isinstance(screw_specs['wear_resistant_cycle_df'], pd.DataFrame):
                screw_specs['wear_resistant_cycle'] = screw_specs['wear_resistant_cycle_df'].to_dict('records')
                del screw_specs['wear_resistant_cycle_df']

        data = {
            "name": name,
            "product_name": product_name,
            "maker": maker,
            "model": model,
            "status": '정상' if status == get_translation('normal') else '고장',
            **details_dict,
            "accessory_specs": json.dumps(accessory_specs, ensure_ascii=False),
            "spare_part_specs": json.dumps(spare_part_specs, ensure_ascii=False),
            "documents": json.dumps(documents, ensure_ascii=False),
            "screw_specs": json.dumps(screw_specs, ensure_ascii=False),
            "oil_specs": json.dumps(oil_specs + [{'notes': oil_notes}, {'aftercare': oil_aftercare}], ensure_ascii=False)
        }

        if new_image_urls:
            data["image_urls"] = new_image_urls

        supabase.from_('equipment').update(data).eq('id', equipment_id).execute()
        st.success("설비 정보가 성공적으로 업데이트되었습니다.")
        st.cache_data.clear()
        st.session_state.selected_eq_id_admin = None
        return True, "설비 정보가 성공적으로 업데이트되었습니다."
    except Exception as e:
        st.error(f"설비 정보 업데이트에 실패했습니다. {e}")
        return False, f"설비 정보 업데이트에 실패했습니다. {e}"

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

def add_log(equipment_id, engineer, action, notes, maintenance_date, maintenance_time, image_urls=None, cost=0.0):
    combined_dt = datetime.combine(maintenance_date, maintenance_time)
    supabase.from_('maintenance_logs').insert({
        'equipment_id': equipment_id,
        'maintenance_date': combined_dt.isoformat(),
        'engineer': engineer,
        'action': action,
        'notes': notes,
        'image_urls': image_urls,
        'cost': cost
    }).execute()
    st.success("정비 이력 추가 완료")
    st.cache_data.clear()

def update_log(log_id, engineer, action, notes, uploaded_images):
    if uploaded_images:
        new_image_urls = update_log_images(log_id, uploaded_images)
        supabase.from_('maintenance_logs').update({
            'engineer': engineer,
            'action': action,
            'notes': notes,
            'image_urls': new_image_urls
        }).eq('id', log_id).execute()
    else:
        supabase.from_('maintenance_logs').update({
            'engineer': engineer,
            'action': action,
            'notes': notes
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

# ------------------------------------------------------
# 5. 다국어 지원 딕셔너리
# ------------------------------------------------------
TRANSLATIONS = {
    'ko': {
        'title': '공장 설비 관리 시스템',
        'login_title': '로그인',
        'select_factory': '공장 선택',
        'enter_password': '비밀번호',
        'login_button': '로그인',
        'login_success': '로그인 성공',
        'login_fail': '비밀번호 오류',
        'current_factory': '현재 공장',
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
        'col_image_urls': '첨부 이미지 URL',
        "product_name": "제품 이름",
        "serial_number": "일련번호",
        "production_date": "제조일",
        "acquisition_cost": "취득 원가",
        "acquisition_date": "취득일",
        "acquisition_basis": "취득 근거",
        "purchase_date": "구입일",
        "installation_location": "설치 위치",
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
        'material_spec_description': '재료 사양'
    },
    'vi': {
        'title': 'Hệ thống Quản lý Thiết bị Nhà máy',
        'login_title': 'Đăng nhập',
        'select_factory': 'Chọn nhà máy',
        'enter_password': 'Mật khẩu',
        'login_button': 'Đăng nhập',
        'login_success': 'Đăng nhập thành công',
        'login_fail': 'Mật khẩu sai',
        'current_factory': 'Nhà máy hiện tại',
        'logout': 'Đăng xuất',
        'dashboard': 'Trang chủ',
        'add_equipment': 'Thêm thiết bị',
        'add_maintenance_log': 'Thêm lịch sử bảo trì',
        'view_maintenance_log': 'Xem lịch sử bảo trì',
        'record_status': 'Ghi lại trạng thái',
        'admin_mode': 'Quản trị viên',
        'no_equipment_registered': 'Chưa có thiết bị nào được đăng ký. Hãy thử thêm một thiết bị mới.',
        'status': 'Trạng thái',
        'normal': 'Bình thường',
        'faulty': 'Hỏng',
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
        "product_name": "Tên sản phẩm",
        "serial_number": "Số seri",
        "production_date": "Ngày sản xuất",
        "acquisition_cost": "Giá mua lại",
        "acquisition_date": "Ngày mua lại",
        "acquisition_basis": "Cơ sở mua lại",
        "purchase_date": "Ngày mua",
        "installation_location": "Vị trí lắp đặt",
        "min_mold_thickness": "Độ dày khuôn tối thiểu",
        "max_mold_thickness": "Độ dày khuôn tối đa",
        "tie_bar_spacing": "Khoảng cách thanh giằng",
        "plate_thickness": "Độ dày tấm",
        "oil_flow_rate": "Tốc độ dòng dầu",
        "max_displacement": "Độ dịch chuyển tối đa",
        "total_weight": "Tổng trọng lượng"
    },
    'th': {
        'title': 'ระบบจัดการอุปกรณ์โรงงาน',
        'login_title': 'เข้าสู่ระบบ',
        'select_factory': 'เลือกโรงงาน',
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
        'admin_mode': 'ผู้ดูแลระบบ',
        'no_equipment_registered': 'ยังไม่มีอุปกรณ์ที่ลงทะเบียน โปรดลองเพิ่มอุปกรณ์ใหม่',
        'capacity_specs': 'ปริมาณและข้อมูลจำเพาะ',
        'motor_capacity_specs': 'ความจุ MOTOR',
        'heater_capacity_specs': 'ความจุของฮีตเตอร์',
        'total_weight': 'น้ำหนักรวมเครื่องจักร (ตัน)',
        'add_row_instruction': 'กดปุ่ม '+' ในตารางเพื่อเพิ่มแถว',
        'status': 'สถานะ',
        'normal': 'ปกติ',
        'faulty': 'ชำรุด',
        'change_status': 'เปลี่ยนสถานะ',
        'notes': 'หมายเหตุ',
        'record_button': 'บันทึก',
        'recent_maintenance_logs': 'ประวัติการบำรุงรักษาล่าสุด (สูงสุด 5 รายการ)',
        'no_recent_logs': 'ไม่มีประวัติการบำรุงรักษาล่าสุด',
        'equipment_name': 'ชื่ออุปกรณ์',
        'maker': 'ผู้ผลิต',
        'model': 'รุ่น',
        'details': 'รายละเอียด',
        'upload_image': 'รูปภาพอุปกรณ์ (สามารถเลือกได้หลายไฟล์)',
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
        "product_name": "ชื่อผลิตภัณฑ์",
        "serial_number": "หมายเลขซีเรียล",
        "production_date": "วันที่ผลิต",
        "acquisition_cost": "ต้นทุนการได้มา",
        "acquisition_date": "วันที่ได้มา",
        "acquisition_basis": "เกณฑ์การได้มา",
        "purchase_date": "วันที่ซื้อ",
        "installation_location": "สถานที่ติดตั้ง",
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
        'record_status': 'Registrar estado',
        'admin_mode': 'Administrador',
        'no_equipment_registered': 'No hay equipos registrados. Intente añadir uno nuevo.',
        'add_row_instruction': 'Presiona el botón '+' en la tabla para agregar una fila.',
        'capacity_specs': 'Capacidad y especificaciones',
        'motor_capacity_specs': 'Capacidad del MOTOR',
        'heater_capacity_specs': 'Capacidad del calentador',
        'total_weight': 'Peso total de la máquina (ton)',
        'status': 'Estado',
        'normal': 'Normal',
        'faulty': 'Defectuoso',
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
        'add_success': 'Equipo añadido con éxito',
        'select_equipment': 'Seleccionar equipo para mantenimiento',
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
        "product_name": "Nombre del producto",
        "serial_number": "Número de serie",
        "production_date": "Fecha de producción",
        "acquisition_cost": "Costo de adquisición",
        "acquisition_date": "Fecha de adquisición",
        "acquisition_basis": "Base de adquisición",
        "purchase_date": "Fecha de compra",
        "installation_location": "Ubicación de la instalación",
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
        st.session_state.oil_specs = []
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
    header_cols = st.columns([1, 1, 1, 0.1, 0.1, 0.1, 0.1, 0.3])
    with header_cols[7]:
        if st.button(get_translation('logout'), key='logout_btn'):
            st.session_state.authenticated = False
            st.session_state.current_factory = None
            st.rerun()

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
                status_color = "green" if eq.get('status') == '정상' else "red"
                with st.expander(
                        f"[{get_translation('normal') if eq.get('status') == '정상' else get_translation('faulty')}] {eq['name']} ({eq.get('model', '')})",
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
                            new_status = st.radio(get_translation('change_status'), [f'🟢 {get_translation("normal")}', f'🔴 {get_translation("faulty")}'], index=0 if eq.get('status') == '정상' else 1)
                            notes = st.text_area(get_translation('notes'))
                            if st.form_submit_button(get_translation('record_button')):
                                final_status = '정상' if new_status.startswith('🟢') else '고장'
                                add_status_history(eq['id'], final_status, notes, history_date, history_time)
                                st.rerun()
                    with col2:
                        # 설비 정보 10개씩 2줄로 표시
                        st.subheader(get_translation('equipment_details'))
                        details = [
                            (get_translation('maker'), eq.get('maker', 'N/A')),
                            (get_translation('model'), eq.get('model', 'N/A')),
                            (get_translation('status'), f":{status_color}-circle: {eq.get('status', 'N/A')}"),
                            (get_translation('product_name'), eq.get('product_name', 'N/A')),
                            (get_translation('serial_number'), eq.get('serial_number', 'N/A')),
                            (get_translation('production_date'), eq.get('production_date', 'N/A')),
                            (get_translation('acquisition_cost'), eq.get('acquisition_cost', 'N/A')),
                            (get_translation('acquisition_date'), eq.get('acquisition_date', 'N/A')),
                            (get_translation('acquisition_basis'), eq.get('acquisition_basis', 'N/A')),
                            (get_translation('purchase_date'), eq.get('purchase_date', 'N/A')),
                            (get_translation('installation_location'), eq.get('installation_location', 'N/A')),
                            (get_translation('motor_capacity_specs'), eq.get('motor_capacity', 'N/A')),
                            (get_translation('heater_capacity_specs'), eq.get('heater_capacity', 'N/A')),
                            (get_translation('min_mold_thickness'), eq.get('min_mold_thickness', 'N/A')),
                            (get_translation('max_mold_thickness'), eq.get('max_mold_thickness', 'N/A')),
                            (get_translation('tie_bar_spacing'), eq.get('tie_bar_spacing', 'N/A')),
                            (get_translation('plate_thickness'), eq.get('plate_thickness', 'N/A')),
                            (get_translation('oil_flow_rate'), eq.get('oil_flow_rate', 'N/A')),
                            (get_translation('max_displacement'), eq.get('max_displacement', 'N/A')),
                            (get_translation('total_weight'), eq.get('total_weight', 'N/A')),
                        ]
                        first_row = details[:10]
                        second_row = details[10:]
                        col_row1, col_row2 = st.columns(2)
                        with col_row1:
                            for label, value in first_row:
                                st.markdown(f"**{label}:** {value}")
                        with col_row2:
                            for label, value in second_row:
                                st.markdown(f"**{label}:** {value}")
                    
                        # 부속기기 사양
                        st.markdown("---")
                        st.subheader(get_translation('accessory_specs'))
                        try:
                            accessory_specs = json.loads(eq.get('accessory_specs', '[]'))
                            if accessory_specs:
                                accessory_df = pd.DataFrame(accessory_specs)
                                st.dataframe(
                                    accessory_df.rename(columns={
                                        '부속기기 명': get_translation('col_accessory_name'),
                                        '형식': get_translation('col_accessory_type'),
                                        '제작번호': get_translation('col_accessory_serial'),
                                        '용량 및 규격': get_translation('col_capacity_spec'),
                                        '제조처': get_translation('col_maker'),
                                        '비고': get_translation('col_notes')
                                    }),
                                    width='stretch'
                                )
                            else:
                                st.info(f"{get_translation('accessory_specs')} 없음")
                        except:
                            st.info(f"{get_translation('accessory_specs')} 데이터 로드 오류")
                    
                        # SPARE PART 사양
                        st.markdown("---")
                        st.subheader(get_translation('spare_part_specs'))
                        try:
                            spare_part_specs = json.loads(eq.get('spare_part_specs', '[]'))
                            if spare_part_specs:
                                spare_part_df = pd.DataFrame(spare_part_specs)
                                st.dataframe(
                                    spare_part_df.rename(columns={
                                        'SPARE PART': get_translation('col_spare_part'),
                                        '교체 주기': get_translation('col_maintenance_cycle'),
                                        '교체 일자': get_translation('col_replacement_date')
                                    }),
                                    width='stretch'
                                )
                            else:
                                st.info(f"{get_translation('spare_part_specs')} 없음")
                        except:
                            st.info(f"{get_translation('spare_part_specs')} 데이터 로드 오류")
                    
                        # 문서
                        st.markdown("---")
                        st.subheader(get_translation('documents'))
                        try:
                            documents = json.loads(eq.get('documents', '[]'))
                            if documents:
                                documents_df = pd.DataFrame(documents)
                                st.dataframe(
                                    documents_df.rename(columns={
                                        '기술 자료명': get_translation('col_doc_name'),
                                        '취급 설명서': get_translation('col_manual'),
                                        '전기 도면': get_translation('col_electric_drawing'),
                                        '유.증압도면': get_translation('col_hydraulic_drawing'),
                                        '윤활 기준표': get_translation('col_lubrication_std')
                                    }),
                                    width='stretch'
                                )
                            else:
                                st.info(f"{get_translation('documents')} 없음")
                        except:
                            st.info(f"{get_translation('documents')} 데이터 로드 오류")
                    
                        # 재료 사양
                        st.markdown("---")
                        st.subheader(get_translation('screw_specs'))
                        material_specs = """
                        A: 일반 수지류(PP, PE, ABS, POM, PMMA, PC, PET)  
                        B: GLASS WOOL 포함율 30% 이내(PC-GF, POM-GF, PA-GF, PBT-GF)  
                        C: GLASS WOOL 포함율 30% 이상(난연 ABS, 난연 PC, 난연 PBI, NYLON6,66)  
                        D: 400℃ 이상 온도 사용 제품
                        """
                        st.markdown(material_specs)
                    
                        # 기타사항
                        st.markdown("---")
                        st.subheader(get_translation('other_notes'))
                        other_notes = """
                        1. 윤활유 MARKER 측의 점도 확인 후 사용 여부 결정하며 3개월/1회 점도 측정하여 부적합 시 교체한다.  
                        *점도 관리 기준: 제조 MARKER의 시험 성적서 참조
                        """
                        st.markdown(other_notes)
                    
                        # 작동유 사양
                        st.markdown("---")
                        st.subheader(get_translation('oil_specs'))
                        try:
                            oil_specs = json.loads(eq.get('oil_specs', '[]'))
                            oil_specs_data = [item for item in oil_specs if 'notes' not in item and 'aftercare' not in item]
                            if oil_specs_data:
                                oil_df = pd.DataFrame(oil_specs_data)
                                st.dataframe(
                                    oil_df.rename(columns={
                                        '구분': get_translation('col_category'),
                                        '적용 작동유 SPCE': get_translation('col_applicable_oil'),
                                        '교체 주기': get_translation('col_maintenance_cycle')
                                    }),
                                    width='stretch'
                                )
                            else:
                                st.info(f"{get_translation('oil_specs')} 없음")
                            oil_notes = next((item['notes'] for item in oil_specs if 'notes' in item), '')
                            oil_aftercare = next((item['aftercare'] for item in oil_specs if 'aftercare' in item), '')
                            if oil_notes:
                                st.markdown(f"**{get_translation('oil_notes')}:** {oil_notes}")
                            if oil_aftercare:
                                st.markdown(f"**{get_translation('other_notes')}:** {oil_aftercare}")
                        except:
                            st.info(f"{get_translation('oil_specs')} 데이터 로드 오류")
                    
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
                                    'notes': get_translation('col_notes'),
                                    'image_urls': get_translation('col_image_urls')
                                })[[get_translation('col_log_id'), get_translation('maintenance_date'),
                                    get_translation('col_engineer'), get_translation('col_action'),
                                    get_translation('col_notes'), get_translation('col_image_urls')]],
                                width='stretch'
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

        with st.form("add_equipment_form"):
            st.markdown(f"##### {get_translation('basic_info')}")
            name = st.text_input(get_translation('equipment_name'), key="add_eq_name")
            product_name = st.text_input(get_translation('product_name'), key="add_eq_product_name")
            maker = st.text_input(get_translation('maker'), key="add_eq_maker")
            model = st.text_input(get_translation('model'), key="add_eq_model")
            serial_number = st.text_input(get_translation('serial_number'), key="add_eq_serial_number")
            production_date = st.date_input(get_translation('production_date'), key="add_eq_production_date")
            acquisition_cost = st.text_input(get_translation('acquisition_cost'), key="add_eq_acquisition_cost")
            acquisition_date = st.date_input(get_translation('acquisition_date'), key="add_eq_acquisition_date")
            acquisition_basis = st.text_input(get_translation('acquisition_basis'), key="add_eq_acquisition_basis")
            purchase_date = st.date_input(get_translation('purchase_date'), key="add_eq_purchase_date")
            installation_location = st.text_input(get_translation('installation_location'), key="add_eq_installation_location")
            min_mold_thickness = st.text_input(get_translation('min_mold_thickness'), key="add_eq_min_mold_thickness")
            max_mold_thickness = st.text_input(get_translation('max_mold_thickness'), key="add_eq_max_mold_thickness")
            tie_bar_spacing = st.text_input(get_translation('tie_bar_spacing'), key="add_eq_tie_bar_spacing")
            plate_thickness = st.text_input(get_translation('plate_thickness'), key="add_eq_plate_thickness")
            oil_flow_rate = st.text_input(get_translation('oil_flow_rate'), key="add_eq_oil_flow_rate")
            max_displacement = st.text_input(get_translation('max_displacement'), key="add_eq_max_displacement")
            motor_capacity = st.text_input(get_translation('motor_capacity_specs'), key="add_eq_motor_capacity")
            heater_capacity = st.text_input(get_translation('heater_capacity_specs'), key="add_eq_heater_capacity")
            total_weight = st.text_input(get_translation('total_weight'), key="add_eq_total_weight")
            st.markdown("---")

            # 부속기기 사양
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
                # 순번 자동 업데이트
                for idx, spec in enumerate(st.session_state.accessory_specs):
                    spec['순번'] = idx + 1
                if st.session_state.accessory_specs:
                    st.write(f"**현재 {len(st.session_state.accessory_specs)}개의 부속기기가 등록되어 있습니다.**")
            st.markdown("---")

            # SPARE PART 사양
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

            # 문서
            with st.expander(get_translation('documents'), expanded=False):
                st.markdown(f"**{get_translation('add_row_instruction')}**")
                documents_df = pd.DataFrame(
                    st.session_state.documents if st.session_state.documents else [],
                    columns=['기술 자료명', '취급 설명서', '전기 도면', '유.증압도면', '윤활 기준표']
                )
                edited_documents_df = st.data_editor(
                    documents_df.rename(columns={
                        '기술 자료명': get_translation('col_doc_name'),
                        '취급 설명서': get_translation('col_manual'),
                        '전기 도면': get_translation('col_electric_drawing'),
                        '유.증압도면': get_translation('col_hydraulic_drawing'),
                        '윤활 기준표': get_translation('col_lubrication_std')
                    }),
                    num_rows="dynamic",
                    width='stretch',
                    key="documents_data_editor"
                )
                st.session_state.documents = edited_documents_df.rename(columns={
                    get_translation('col_doc_name'): '기술 자료명',
                    get_translation('col_manual'): '취급 설명서',
                    get_translation('col_electric_drawing'): '전기 도면',
                    get_translation('col_hydraulic_drawing'): '유.증압도면',
                    get_translation('col_lubrication_std'): '윤활 기준표'
                }).to_dict('records')
                if st.session_state.documents:
                    st.write(f"**현재 {len(st.session_state.documents)}개의 문서가 등록되어 있습니다.**")

            # 스크류 사양
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
                cols_tables_and_note = st.columns([7, 3])
                with cols_tables_and_note[0]:
                    st.markdown("###### 2) 일반용 SCREW")
                    st.session_state.screw_specs['general_cycle_df'] = st.data_editor(
                        pd.DataFrame(st.session_state.screw_specs['general_cycle']),
                        key="general_screw_cycle_editor",
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
                    st.session_state.screw_specs['wear_resistant_cycle_df'] = st.data_editor(
                        pd.DataFrame(st.session_state.screw_specs['wear_resistant_cycle']),
                        key="wear_resistant_screw_cycle_editor",
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

            # 작동유 사양
            with st.expander(get_translation('oil_specs'), expanded=False):
                st.markdown(f"**{get_translation('add_row_instruction')}**")
                if len(st.session_state.oil_specs) > 0:
                    st.write(f"**현재 {len(st.session_state.oil_specs)}개의 작동유 항목이 등록되어 있습니다.**")
                    oil_df = pd.DataFrame(st.session_state.oil_specs)
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
                else:
                    st.info(f"{get_translation('oil_specs')} 없음")
            st.markdown("---")

            # 기타사항 및 이미지 업로드
            st.session_state.other_notes = st.text_area(get_translation('other_notes'), value=st.session_state.get('other_notes', ''), key="add_other_notes")
            uploaded_images = st.file_uploader(get_translation('upload_image'), type=['png', 'jpg', 'jpeg'], accept_multiple_files=True, key="add_eq_images")
            st.markdown("**1년 경과 후 사후관리 방안:**")
            st.markdown("*아래에 내용을 작성하세요. 줄바꿈이 자동으로 적용됩니다.*")
            st.session_state.oil_aftercare = st.text_area("사후관리 내용", value=st.session_state.get('oil_aftercare', ''), key="add_oil_aftercare", height=100, label_visibility="collapsed")

            # 설비 추가 최종 제출 버튼
            if st.form_submit_button(get_translation('add_equipment_button'), type="primary"):
                image_urls_str = upload_images(uploaded_images) if uploaded_images else ""
                if factory_id and name and model:
                    screw_specs_to_add = {
                        'material_spec_description': st.session_state.screw_specs.get('material_spec_description', ''),
                        'screw_type_general': st.session_state.screw_specs.get('screw_type_general', ''),
                        'applicable_general': st.session_state.screw_specs.get('applicable_general', ''),
                        'screw_type_wear': st.session_state.screw_specs.get('screw_type_wear', ''),
                        'applicable_wear': st.session_state.screw_specs.get('applicable_wear', ''),
                        'general_cycle': st.session_state.screw_specs['general_cycle_df'].to_dict('records'),
                        'wear_resistant_cycle': st.session_state.screw_specs['wear_resistant_cycle_df'].to_dict('records')
                    }
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
                        'min_mold_thickness': min_mold_thickness,
                        'max_mold_thickness': max_mold_thickness,
                        'tie_bar_spacing': tie_bar_spacing,
                        'plate_thickness': plate_thickness,
                        'oil_flow_rate': oil_flow_rate,
                        'max_displacement': max_displacement,
                        'total_weight': total_weight,
                        'other_notes': st.session_state.other_notes
                    }
                    success, message = add_equipment(
                        factory_id=factory_id,
                        name=name,
                        model=model,
                        details_dict=details_dict,
                        accessory_specs=st.session_state.accessory_specs,
                        spare_part_specs=st.session_state.spare_part_specs,
                        documents=st.session_state.documents,
                        screw_specs=screw_specs_to_add,
                        oil_specs=st.session_state.oil_specs + [{'notes': '1년 경과 후 사후관리 방안'}, {'aftercare': st.session_state.oil_aftercare}],
                        image_urls=image_urls_str
                    )
                    if success:
                        reset_add_equipment_form_state()
                        st.session_state.other_notes = ''
                        st.session_state.oil_aftercare = ''
                        st.success("설비가 성공적으로 추가되었습니다.")
                        st.rerun()
                    else:
                        st.error(f"설비 추가 실패: {message}")
                else:
                    st.error("필수 정보를 모두 입력해주세요: 설비명, 모델")

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
                    action = st.text_input(get_translation('maintenance_action'))
                    notes = st.text_area(get_translation('notes'))
                    col_dt1, col_dt2 = st.columns(2)
                    with col_dt1:
                        maintenance_date = st.date_input(get_translation('maintenance_date'), value=date.today())
                    with col_dt2:
                        maintenance_time = st.time_input(get_translation('maintenance_time'), value=time(datetime.now().hour, datetime.now().minute))
                    cost = st.number_input("정비 비용", min_value=0.0, format="%.2f", key="add_log_cost")
                    uploaded_images = st.file_uploader(get_translation('upload_image'), type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
                    submitted = st.form_submit_button(get_translation('add_log_button'))
                    if submitted:
                        image_urls = upload_images(uploaded_images) if uploaded_images else None
                        add_log(selected_eq_id, engineer, action, notes, maintenance_date, maintenance_time, image_urls, cost)
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
                                            st.image(url.strip(), use_column_width=True)
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
                    status = st.radio(get_translation('change_status'), [get_translation('normal'), get_translation('faulty')])
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

            # 설비 수정/삭제
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
                        with st.form("update_equipment_form"):
                            name = st.text_input(get_translation('equipment_name'), value=eq_data['name'], key="update_eq_name")
                            product_name = st.text_input(get_translation('product_name'), value=eq_data.get('product_name', ''), key="update_eq_product_name")
                            maker = st.text_input(get_translation('maker'), value=eq_data.get('maker', ''), key="update_eq_maker")
                            model = st.text_input(get_translation('model'), value=eq_data['model'], key="update_eq_model")
                            serial_number = st.text_input(get_translation('serial_number'), value=eq_data.get('serial_number', ''), key="update_eq_serial_number")
                            production_date = st.date_input(get_translation('production_date'), value=get_date_value(eq_data.get('production_date', None)), key="update_eq_production_date")
                            acquisition_cost = st.text_input(get_translation('acquisition_cost'), value=eq_data.get('acquisition_cost', ''), key="update_eq_acquisition_cost")
                            acquisition_date = st.date_input(get_translation('acquisition_date'), value=get_date_value(eq_data.get('acquisition_date', None)), key="update_eq_acquisition_date")
                            acquisition_basis = st.text_input(get_translation('acquisition_basis'), value=eq_data.get('acquisition_basis', ''), key="update_eq_acquisition_basis")
                            purchase_date = st.date_input(get_translation('purchase_date'), value=get_date_value(eq_data.get('purchase_date', None)), key="update_eq_purchase_date")
                            installation_location = st.text_input(get_translation('installation_location'), value=eq_data.get('installation_location', ''), key="update_eq_installation_location")
                            min_mold_thickness = st.text_input(get_translation('min_mold_thickness'), value=eq_data.get('min_mold_thickness', ''), key="update_eq_min_mold_thickness")
                            max_mold_thickness = st.text_input(get_translation('max_mold_thickness'), value=eq_data.get('max_mold_thickness', ''), key="update_eq_max_mold_thickness")
                            tie_bar_spacing = st.text_input(get_translation('tie_bar_spacing'), value=eq_data.get('tie_bar_spacing', ''), key="update_eq_tie_bar_spacing")
                            plate_thickness = st.text_input(get_translation('plate_thickness'), value=eq_data.get('plate_thickness', ''), key="update_eq_plate_thickness")
                            oil_flow_rate = st.text_input(get_translation('oil_flow_rate'), value=eq_data.get('oil_flow_rate', ''), key="update_eq_oil_flow_rate")
                            max_displacement = st.text_input(get_translation('max_displacement'), value=eq_data.get('max_displacement', ''), key="update_eq_max_displacement")
                            motor_capacity = st.text_input(get_translation('motor_capacity_specs'), value=eq_data.get('motor_capacity', ''), key="update_eq_motor_capacity")
                            heater_capacity = st.text_input(get_translation('heater_capacity_specs'), value=eq_data.get('heater_capacity', ''), key="update_eq_heater_capacity")
                            total_weight = st.text_input(get_translation('total_weight'), value=eq_data.get('total_weight', ''), key="update_eq_total_weight")
                            status = st.radio(get_translation('status'), [get_translation('normal'), get_translation('faulty')], index=0 if eq_data['status'] == '정상' else 1)
                            st.markdown("---")
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
                                        "교체 일자": st.column_config.DateColumn(
                                            "교체 일자",
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
                                        '윤활 기준표': get_translation('col_lubrication_std')
                                    }),
                                    num_rows="dynamic",
                                    width='stretch'
                                )
                                st.session_state.edit_documents = edited_documents_df.rename(columns={
                                    get_translation('col_doc_name'): '기술 자료명',
                                    get_translation('col_manual'): '취급 설명서',
                                    get_translation('col_electric_drawing'): '전기 도면',
                                    get_translation('col_hydraulic_drawing'): '유.증압도면',
                                    get_translation('col_lubrication_std'): '윤활 기준표'
                                }).to_dict('records')
                            st.markdown("---")
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
                            cols_tables_and_note = st.columns([7, 3])
                            with cols_tables_and_note[0]:
                                st.markdown("###### 2) 일반용 SCREW")
                                st.session_state.edit_screw_specs['general_cycle_df'] = st.data_editor(
                                    pd.DataFrame(st.session_state.edit_screw_specs.get('general_cycle_df', [{'해당 사양': '교체 주기 (월)', 'A': '5', 'B': '5', 'C': '3', 'D': '3'}])),
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
                                    pd.DataFrame(st.session_state.edit_screw_specs.get('wear_resistant_cycle_df', [{'해당 사양': '교체 주기 (월)', 'A': '10', 'B': '10', 'C': '5', 'D': '5'}])),
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

                            st.session_state.edit_oil_notes = st.text_area("작동유 점도 측정 방법", value=st.session_state.edit_oil_notes, key="update_oil_notes", height=100)
                            st.markdown("**1년 경과 후 사후관리 방안:**")
                            st.markdown("*아래에 내용을 작성하세요. 줄바꿈이 자동으로 적용됩니다.*")
                            st.session_state.edit_oil_aftercare = st.text_area("사후관리 내용", value=st.session_state.edit_oil_aftercare, key="update_oil_aftercare", height=100, label_visibility="collapsed")

                            st.markdown("---")
                            # other_notes를 세션 상태로 관리
                            st.session_state.edit_other_notes = st.text_area(get_translation('other_notes'), value=eq_data.get('other_notes', ''), key="update_other_notes")
                            uploaded_images = st.file_uploader(get_translation('upload_image'), type=['png', 'jpg', 'jpeg'], accept_multiple_files=True, key="update_eq_images")

                            # 설비 수정 최종 제출 버튼
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button(get_translation('update_button'), type="primary"):
                                    screw_specs_to_update = {
                                        'material_spec_description': st.session_state.edit_screw_specs.get('material_spec_description', ''),
                                        'screw_type_general': st.session_state.edit_screw_specs.get('screw_type_general', ''),
                                        'applicable_general': st.session_state.edit_screw_specs.get('applicable_general', ''),
                                        'screw_type_wear': st.session_state.edit_screw_specs.get('screw_type_wear', ''),
                                        'applicable_wear': st.session_state.edit_screw_specs.get('applicable_wear', ''),
                                        'general_cycle': st.session_state.edit_screw_specs['general_cycle_df'].to_dict('records'),
                                        'wear_resistant_cycle': st.session_state.edit_screw_specs['wear_resistant_cycle_df'].to_dict('records')
                                    }
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
                                        'min_mold_thickness': min_mold_thickness,
                                        'max_mold_thickness': max_mold_thickness,
                                        'tie_bar_spacing': tie_bar_spacing,
                                        'plate_thickness': plate_thickness,
                                        'oil_flow_rate': oil_flow_rate,
                                        'max_displacement': max_displacement,
                                        'total_weight': total_weight,
                                        'other_notes': st.session_state.edit_other_notes  # 세션 상태에서 other_notes 가져오기
                                    }
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
                                        oil_notes=st.session_state.edit_oil_notes,
                                        oil_aftercare=st.session_state.edit_oil_aftercare
                                    )
                                    if success:
                                        st.session_state.edit_other_notes = ''  # 폼 제출 후 edit_other_notes 초기화
                                        st.success("설비 정보가 성공적으로 업데이트되었습니다.")
                                        st.rerun()
                                    else:
                                        st.error(f"설비 업데이트 실패: {message}")
                            with col2:
                                if st.form_submit_button(get_translation('delete_button'), type="primary"):
                                    delete_equipment(st.session_state.selected_eq_id_admin)
                                    st.session_state.edit_other_notes = ''  # 삭제 후 edit_other_notes 초기화
                                    st.success("설비가 성공적으로 삭제되었습니다.")
                                    st.rerun()

            # 정비 이력 수정/삭제
            with admin_tabs[3]:
                st.header(get_translation('update_log_admin'))
                logs_list = get_maintenance_logs()
                if not logs_list:
                    st.warning("정비 이력이 없습니다.")
                else:
                    log_options = {f"ID: {log['id']} | 날짜: {log['maintenance_date']} | 작업: {log['action']}": log['id'] for log in logs_list}
                    selected_log_id_admin = st.selectbox(get_translation('select_log_admin'), options=list(log_options.keys()), key='admin_log_select')
                    selected_log_id = log_options.get(selected_log_id_admin, None)

                    if selected_log_id:
                        log_data = next((log for log in logs_list if log['id'] == selected_log_id), None)
                        if log_data:
                            with st.form("update_log_form"):
                                engineer = st.text_input(get_translation('col_engineer'), value=log_data['engineer'])
                                action = st.text_input(get_translation('col_action'), value=log_data['action'])
                                notes = st.text_area(get_translation('col_notes'), value=log_data['notes'])
                                uploaded_images = st.file_uploader(get_translation('upload_image'), type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
                                col1, col2 = st.columns(2)
                                with col1:
                                    if st.form_submit_button(get_translation('update_button')):
                                        update_log(selected_log_id, engineer, action, notes, uploaded_images)
                                        st.rerun()
                                with col2:
                                    if st.form_submit_button(get_translation('delete_button')):
                                        delete_log(selected_log_id)
                                        st.rerun()

            # 상태 기록 수정/삭제
            with admin_tabs[4]:
                st.header(get_translation('update_status_admin'))
                # factory_id를 전달하여 get_status_history 호출
                status_history = get_status_history(factory_id=factory_id)
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
                                status = st.radio(get_translation('status'), [get_translation('normal'), get_translation('faulty')], index=0 if status_data['status'] == get_translation('normal') else 1)
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
