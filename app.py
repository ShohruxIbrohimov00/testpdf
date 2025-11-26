import json
from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import random
from sqlalchemy import exc
from datetime import datetime
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
import os 


# ==========================================================
# KONFIGURATSIYA QISMI (FAQAT PostgreSQL ga moslandi)
# ==========================================================

# 1. Renderdan keladigan DATABASE_URL ni olish
database_url = os.environ.get('DATABASE_URL')

# 2. Agar URL 'postgres://' bilan boshlansa, uni 'postgresql://' ga o'zgartirish
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

# 🔥 MUHIM TEKSHIRUV: Agar DATABASE_URL topilmasa, Ilovani ishga tushirmaslik (Render uchun zarur)
if not database_url:
    # Bu yerda biz SQLite variantini butunlay olib tashladik
    raise EnvironmentError("DATABASE_URL muhit o'zgaruvchisi topilmadi. PostgreSQL ulanish manzili majburiy.")

app = Flask(__name__)
app.config['SECRET_KEY'] = '42e9f7a1c3d8b5e0a6f4d2c8b1a9f3e7d4c1b8a5f2e6d3c7b0a8f9e6d5c2b9a4'
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
ADMIN_USERNAME = "AdminTest"
ADMIN_PASSWORD = "Salom1234"

s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

def generate_test_token(test_id, code):
    """Test ID va Code ni shifrlab, noyob URL-safe token yaratadi."""
    payload = {'id': test_id, 'code': code}
    # 'test-start-salt' tokenni faqat test boshlash maqsadida ishlatilishini ta'minlaydi
    return s.dumps(payload, salt='test-start-salt') 

def verify_test_token(token):
    """Tokenni deshifrlaydi va haqiqiyligini tekshiradi."""
    try:
        # max_age parametrini qo'shib, tokenning amal qilish muddatini ham belgilash mumkin (masalan, 604800 sekund = 1 hafta)
        payload = s.loads(token, salt='test-start-salt') 
        return payload
    except (SignatureExpired, BadTimeSignature):
        return None # Token amal qilish muddati o'tgan yoki noto'g'ri imzo
    except Exception:
        return None # Boshqa xato (masalan, noto'g'ri format)


# ==========================================================
# MA'LUMOTLAR BAZASI MODELLARI
# ==========================================================

class Test(db.Model):
    __tablename__ = 'tests'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(6), unique=True, nullable=False)
    questions_count = db.Column(db.Integer, nullable=False)
    variants_count = db.Column(db.Integer, nullable=False)
    
    pdf_drive_link = db.Column(db.Text, nullable=True) 
    answers_json = db.Column(db.Text, nullable=True)
    results_json = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'questions': self.questions_count,
            'variants': self.variants_count,
            'answers': json.loads(self.answers_json) if self.answers_json else {},
            'results': json.loads(self.results_json) if self.results_json else [],
            'pdf_link': self.pdf_drive_link  
        }

class StudentSession(db.Model):
    __tablename__ = 'student_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), unique=True, nullable=False)  # noyob ID
    test_id = db.Column(db.Integer, db.ForeignKey('tests.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'user_id': self.user_id,
            'name': self.name,
            'test_id': self.test_id
        }
# ==========================================================
# QO'SHIMCHA YORDAMCHI FUNKSIYALAR
# ==========================================================



def get_flat_correct_answers(answers_json):
    """answers_json dan faqat javob qiymatini ajratib oladi."""
    if not answers_json:
        return {}
    
    raw_answers = json.loads(answers_json)
    flat_answers = {}
    for q_num_str, data in raw_answers.items():
        flat_answers[q_num_str] = data.get('answer')
    return flat_answers


def get_answer_type(answers_json, q_num_str):
    """Savol turini aniqlaydi (single, multiple, text)."""
    if not answers_json:
        return 'single' # Default
    
    raw_answers = json.loads(answers_json)
    return raw_answers.get(q_num_str, {}).get('type', 'single')

def get_question_types(answers_json):
    """Faqat savol turlari lug'atini qaytaradi."""
    if not answers_json:
        return {}
    
    raw_answers = json.loads(answers_json)
    question_types = {}
    for q_num_str, data in raw_answers.items():
        question_types[q_num_str] = data.get('type', 'single')
    return question_types

# ==========================================================
# API ENDPOINTLAR
# ==========================================================

@app.route('/api/test/create', methods=['POST'])
def create_test():
    try:
        data = request.get_json()
        pdf_preview_link = data.get('pdf_preview_link') 
        
        while True:
            new_code = str(random.randint(100000, 999999))
            if not Test.query.filter_by(code=new_code).first():
                break

        new_test = Test(
            name=data.get('name'),
            code=new_code,
            questions_count=data.get('questions'),
            variants_count=data.get('variants'),
            pdf_drive_link=pdf_preview_link,   
            answers_json=data.get('answers')
        )
        
        db.session.add(new_test)
        db.session.commit()
        
        site_token = generate_test_token(new_test.id, new_code)
        
        return jsonify({
            'status': 'success',
            'test_id': new_test.id,
            'test_code': new_code,
            'site_token': site_token,
            'message': 'Test muvaffaqiyatli yaratildi!'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

#Test ma'lumotlarini olishda pdf_link qaytaramiz
@app.route('/api/test/get_by_code/<code>', methods=['GET'])
def get_test_by_code(code):
    test = Test.query.filter_by(code=code).first()
    if test:
        data = test.to_dict()
        question_types = get_question_types(test.answers_json)
        
        del data['answers']
        del data['results']
        
        data['question_types'] = question_types
        return jsonify(data), 200
    return jsonify({'status': 'error', 'message': 'Kod topilmadi.'}), 404

# Admin panel uchun testlar ro'yxatini yuklash (o'zgarishsiz)
@app.route('/api/tests/load', methods=['GET'])
def load_all_tests():
    try:
        tests = Test.query.all()
        test_list = []
        for t in tests:
            # HAR SAFAR YANGI TOKEN YARATILADI (xavfsiz va to'g'ri!)
            token = generate_test_token(t.id, t.code)
            
            test_list.append({
                'id': t.id,
                'name': t.name,
                'code': t.code,  # admin uchun saqlansa ham bo'ladi, lekin ko'rsatilmaydi
                'questions': t.questions_count,
                'results_count': len(json.loads(t.results_json or '[]')),
                'site_token': token   # BU MAYDON BOʻLISHI SHART!
            })
        
        return jsonify(test_list), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ID bo'yicha test ma'lumotlarini yuklash (o'zgarishsiz)
@app.route('/api/test/get_by_id/<int:test_id>', methods=['GET'])
def get_test_by_id(test_id):
    try:
        test = Test.query.get(test_id)
        if test:
            data = test.to_dict()
            
            question_types = get_question_types(test.answers_json)
            
            del data['answers'] 
            del data['results']
            
            data['question_types'] = question_types
            
            return jsonify(data), 200
        return jsonify({'status': 'error', 'message': 'Test topilmadi.'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Yuklash xatosi: {str(e)}'}), 500

# Natijalarni saqlash va hisoblash (o'zgarishsiz)
@app.route('/api/result/save/<int:test_id>', methods=['POST'])
def save_test_result(test_id):
    try:
        test = Test.query.get(test_id)
        if not test:
            return jsonify({'status': 'error', 'message': 'Test topilmadi.'}), 404
        
        data = request.get_json()
        user_id = data.get('user_id')                    # YANGI: faqat user_id keladi
        student_answers = data.get('student_answers', {})

        if not user_id:
            return jsonify({'status': 'error', 'message': 'Foydalanuvchi ID topilmadi'}), 400

        # user_id orqali ismni topamiz
        session = StudentSession.query.filter_by(user_id=user_id, test_id=test_id).first()
        if not session:
            return jsonify({'status': 'error', 'message': 'Talaba maʼlumotlari topilmadi'}), 404

        student_name = session.name

        # Toʻgʻri javoblarni hisoblash
        correct_answers_flat = get_flat_correct_answers(test.answers_json)
        total_questions = test.questions_count
        correct_count = 0

        for q_num in range(1, total_questions + 1):
            q_str = str(q_num)
            if q_str not in student_answers or q_str not in correct_answers_flat:
                continue

            std_ans = student_answers[q_str]
            corr_ans = correct_answers_flat[q_str]
            if corr_ans is None:
                continue

            q_type = get_answer_type(test.answers_json, q_str)

            if q_type == 'text':
                if isinstance(corr_ans, str) and str(std_ans).strip().lower() == corr_ans.strip().lower():
                    correct_count += 1
            elif q_type == 'multiple':
                if isinstance(corr_ans, list) and isinstance(std_ans, list):
                    if sorted(std_ans) == sorted(corr_ans):
                        correct_count += 1
            elif q_type == 'single':
                if str(std_ans).strip() == str(corr_ans).strip():
                    correct_count += 1

        percentage = round((correct_count / total_questions) * 100) if total_questions > 0 else 0

        # Natija obyekti
        result_entry = {
            'id': user_id,
            'name': student_name,
            'correct': correct_count,
            'wrong': total_questions - correct_count,
            'percentage': percentage,
            'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'answers': student_answers
        }

        # Eski natijalarni olish
        all_results = json.loads(test.results_json) if test.results_json else []

        # Agar oldin topshirgan boʻlsa — yangilaymiz
        existing_idx = next((i for i, r in enumerate(all_results) if r.get('id') == user_id), -1)
        if existing_idx != -1:
            all_results[existing_idx] = result_entry
        else:
            all_results.append(result_entry)

        # Bazaga saqlash
        test.results_json = json.dumps(all_results, ensure_ascii=False)
        db.session.commit()

        return jsonify({
            'status': 'success',
            'result': result_entry,
            'message': 'Natija muvaffaqiyatli saqlandi'
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f'Xatolik: {str(e)}'}), 500
    
# Barcha natijalarni yuklash (o'zgarishsiz)
@app.route('/api/results/all/<int:test_id>', methods=['GET'])
def get_test_results(test_id):
    try:
        test = Test.query.get(test_id)
        if not test:
            return jsonify({'status': 'error', 'message': 'Test topilmadi.'}), 404
        
        results = json.loads(test.results_json) if test.results_json else []
        results.sort(key=lambda x: x.get('percentage', 0), reverse=True)
        
        return jsonify({
            'test_name': test.name,
            'questions_count': test.questions_count,
            'results': results
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Yuklash xatosi: {str(e)}'}), 500

# Faqat bitta natijani yuklash (o'zgarishsiz)
@app.route('/api/result/single/<int:test_id>/<user_id>', methods=['GET'])
def get_single_result(test_id, user_id):
    try:
        test = Test.query.get(test_id)
        if not test:
            return jsonify({'status': 'error', 'message': 'Test topilmadi.'}), 404
        
        all_results = json.loads(test.results_json) if test.results_json else []
        
        result = next((r for r in all_results if str(r['id']) == user_id), None)
        
        if result:
            flat_correct_answers = get_flat_correct_answers(test.answers_json)
            question_types = get_question_types(test.answers_json)
            
            return jsonify({
                'test_info': {'name': test.name, 'questions': test.questions_count},
                'correct_answers': flat_correct_answers,
                'question_types': question_types,
                'result': result
            }), 200
        
        return jsonify({'status': 'error', 'message': 'Natija topilmadi.'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Yuklash xatosi: {str(e)}'}), 500


# ==========================================================
# ADMIN LOGIN API
# ==========================================================

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        # 🔑 Muvaffaqiyatli login. 
        # Haqiqiy loyihada foydalanuvchiga session token beriladi.
        # Hozircha oddiy JSON javobi qaytariladi.
        return jsonify({'status': 'success', 'message': 'Muvaffaqiyatli kirish.', 'token': 'fake_admin_token'}), 200
    else:
        return jsonify({'status': 'error', 'message': 'Login yoki parol noto‘g‘ri.'}), 401
    
# ==========================================================
# SHABLONLARNI TAQDIM ETISH (RENDER TEMPLATES)
# ==========================================================

# Bosh sahifa (o'zgarishsiz)
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin/login')
def admin_login_page():
    # Bu yerda siz Login va Parol kiritish formasini ko'rsatasiz
    # Hozircha bo'sh shablonni render qiladi
    return render_template('admin_login.html')

@app.route('/admin')
def admin_dash():
    return render_template('admin_dash.html')

@app.route('/student_info', methods=['GET'])
def student_info_page():
    test_id = request.args.get('test_id')
    token = request.args.get('token')

    # Agar token yoki id yo'q bo'lsa, xavfsizlik tekshiruviga qaytarish
    if not test_id or not token:
        return redirect(url_for('start_test_page'))

    # Ma'lumot kiritish formasini ko'rsatish
    return render_template('student_info.html', test_id=test_id, token=token)

@app.route('/api/student/register', methods=['POST'])
def register_student():
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        name = data.get('name', '').strip()

        if not test_id or not name or len(name) < 3:
            return jsonify({'status': 'error', 'message': 'Ism toʻliq kiritilmagan'}), 400

        test = Test.query.get(test_id)
        if not test:
            return jsonify({'status': 'error', 'message': 'Test topilmadi'}), 404

        # Noyob user_id yaratish
        import secrets
        user_id = secrets.token_hex(8)  # masalan: a1b2c3d4e5f6

        # Saqlash
        session = StudentSession(
            user_id=user_id,
            test_id=test_id,
            name=name
        )
        db.session.add(session)
        db.session.commit()

        return jsonify({
            'status': 'success',
            'user_id': user_id,
            'message': 'Ism muvaffaqiyatli saqlandi'
        })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    
# Test yaratish sahifasi (o'zgarishsiz)
@app.route('/create')
def create_page():
    return render_template('create_test.html')

# Test yaratildi sahifasi (o'zgarishsiz)
@app.route('/test-created')
def test_created_page():
    # Bu sahifaga endi 'site_token' parametri ham keladi
    return render_template('test_created.html')


# 🔥 YANGI: Tokenni tekshirish va talaba ma'lumotlarini kiritishga yo'naltirish
@app.route('/test/start', methods=['GET'])
def start_test_page():
    # 1. URL dan 'token' ni olish
    token = request.args.get('token')

    if not token:
        # Tokensi kirishni rad etish
        return render_template('error_page.html', 
                               title="Ruxsat Yo'q", 
                               message="Testga kirish uchun noyob link (token) zarur. Iltimos, administrator tomonidan berilgan to‘liq link orqali kiring.")

    # 2. Tokenni tekshirish
    payload = verify_test_token(token)
    
    if not payload:
        # Token noto'g'ri yoki muddati o'tgan
        return render_template('error_page.html', 
                               title="Noto'g'ri Link", 
                               message="Siz foydalanmoqchi bo'lgan test linki noto'g'ri, muddati tugagan yoki buzilgan. Iltimos, admin bilan bog'laning.")

    test_id = payload.get('id')
    test_code = payload.get('code')
    
    # 3. Tokendagi ID va Code bazadagi ma'lumotlarga mos kelishini tekshirish
    test = Test.query.get(test_id)
    if not test or test.code != test_code:
        return render_template('error_page.html', 
                               title="Test Topilmadi", 
                               message="Token haqiqiy, ammo bog'langan test topilmadi yoki kod mos kelmadi. Administratorga murojaat qiling.")

    # 4. Hammasi to'g'ri bo'lsa, foydalanuvchini ism-familiya kiritish sahifasiga yuborish
    # Tokenni keyingi bosqichda ham ishlatish uchun uni parametr sifatida yuboramiz.
    return redirect(url_for('student_info_page', test_id=test_id, token=token))


# Talaba test ishlash sahifasi (o'zgarishsiz, lekin endi faqat /student_info orqali kiriladi)
@app.route('/test/<int:test_id>')
def student_test_page(test_id):
    # Bu routega student_info.html dagi forma post qilingandan so'ng kiriladi
    return render_template('student_test.html', test_id=test_id) 

# Talaba natijasi sahifasi (o'zgarishsiz)
@app.route('/result/<int:test_id>')
def student_result_page(test_id):
    user_id = request.args.get('r', 'anon')
    return render_template('student_result.html', test_id=test_id, user_id=user_id)

# Admin natijalari ro'yxati sahifasi (o'zgarishsiz)
@app.route('/results/admin/<int:test_id>')
def admin_results_page(test_id):
    return render_template('admin_results.html', test_id=test_id)

# app.py faylida /api/test/delete/<int:test_id> route'ini quyidagicha o'zgartiring:

@app.route('/api/test/delete/<int:test_id>', methods=['DELETE'])
def delete_test(test_id):
    try:
        # 1. Testni ID bo'yicha topish
        test_to_delete = Test.query.get(test_id)
        
        if not test_to_delete:
            return jsonify({
                'status': 'error', 
                'message': f'ID={test_id} bo‘lgan test topilmadi.'
            }), 404

        # 🔥 MUAMMONI HAL QILUVCHI QISM:
        # Testni o'chirishdan avval, unga bog'liq barcha StudentSession (ro'yxatdan o'tgan talabalar) yozuvlarini o'chiramiz.
        # Bu, PostgreSQL bazasidagi (Foreign Key) bog'lanish cheklovini (IntegrityError) oldini oladi.
        StudentSession.query.filter_by(test_id=test_id).delete()
        
        # 2. Endi testning o'zini o'chirish
        test_name = test_to_delete.name
        db.session.delete(test_to_delete)
        
        # 3. Amaliyotni yakunlash
        db.session.commit()
        
        # 4. Muvaffaqiyatli javob
        return jsonify({
            'status': 'success', 
            'message': f'"{test_name}" nomli test (ID: {test_id}) muvaffaqiyatli o‘chirildi.'
        }), 200
    
    except exc.SQLAlchemyError as e:
        db.session.rollback()
        # Baza xatolarini qaytarish
        return jsonify({
            'status': 'error', 
            'message': f'Testni o‘chirishda baza xatosi yuz berdi. (DB Rollback): {str(e)}'
        }), 500
        
    except Exception as e:
        db.session.rollback()
        # Boshqa xatolar
        return jsonify({
            'status': 'error', 
            'message': f'Testni o‘chirishda kutilmagan xato: {str(e)}'
        }), 500

        
# Loyihani ishga tushirishdan avval baza faylini yaratish
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
