from datetime import datetime
import os
import json
import logging
import schedule
import time
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ========================
# Configurações
# ========================

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

PORT = int(os.environ.get("PORT", 5000))
DATA_FILE = "referrals.json"
BACKUP_FOLDER = "backups"
SECRET_KEY = "SUA_CHAVE_SECRETA_PARA_MARCAR_COMO_PAGO"

# ========================
# Funções auxiliares para manipular o JSON
# ========================

def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({"referrals": [], "paid_referrals": []}, f)
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_valid_address(addr):
    return addr.startswith("0x") and len(addr) == 42

# ========================
# Backup Automático Diário
# ========================

def backup_json_file():
    if not os.path.exists(BACKUP_FOLDER):
        os.makedirs(BACKUP_FOLDER)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_FOLDER, f"referrals_backup_{timestamp}.json")

    try:
        data = load_data()
        with open(backup_path, "w") as f:
            json.dump(data, f, indent=2)
        logging.info(f"Backup realizado: {backup_path}")
    except Exception as e:
        logging.error(f"Falha ao fazer backup: {e}")

# Agenda o backup diário às 00:00
def start_backup_scheduler():
    schedule.every().day.at("00:00").do(backup_json_file)
    while True:
        schedule.run_pending()
        time.sleep(60)

# ========================
# API Flask - ROTAS
# ========================

@app.route("/api/register-referral", methods=["POST"])
def register_referral():
    data = request.get_json()
    address = data.get("address", "").lower()

    if not is_valid_address(address):
        return jsonify({"error": "Endereço inválido"}), 400

    db = load_data()
    existing = next((item for item in db["referrals"] if item["referrer"] == address), None)
    if not existing:
        db["referrals"].append({
            "referrer": address,
            "referee": "",
            "paid": False
        })
        save_data(db)

    return jsonify({"message": "Link registrado localmente"}), 200

@app.route("/api/use-referral", methods=["POST"])
@limiter.limit("3/minute")
def use_referral():
    data = request.get_json()
    referrer = data.get("referrer", "").lower()
    referee = data.get("referee", "").lower()
    faucet_token = data.get("faucet_token", "")

    if not is_valid_address(referrer) or not is_valid_address(referee):
        return jsonify({"error": "Endereço inválido"}), 400

    if faucet_token != "VALID_FAUCET_USAGE":
        return jsonify({"error": "Token inválido"}), 401

    db = load_data()

    # Verifica se já foi indicado por alguém
    already_referenced = next((item for item in db["referrals"] if item["referee"] == referee), None)
    if already_referenced:
        return jsonify({"error": "Já foi indicado por outra carteira."}), 400

    # Conta número de indicações do referenciador
    total_referrals = sum(1 for item in db["referrals"] if item["referrer"] == referrer)

    if total_referrals >= 200:
        return jsonify({"error": "Limite de indicações atingido"}), 400

    # Registra nova indicação
    db["referrals"].append({
        "referrer": referrer,
        "referee": referee,
        "paid": False
    })

    save_data(db)

    return jsonify({"message": "Indicação registrada!"}), 200

@app.route("/api/referral-status/<address>", methods=["GET"])
def referral_status(address):
    address = address.lower()
    db = load_data()
    referrals = [r for r in db["referrals"] if r["referrer"] == address]
    total = len(referrals)
    paid = sum(1 for r in referrals if r["paid"])
    return jsonify({
        "total_referrals": total,
        "paid": paid,
        "unpaid": total - paid,
        "referrals": referrals
    }), 200

@app.route("/api/payout-list", methods=["GET"])
def payout_list():
    db = load_data()
    unpaid = [r for r in db["referrals"] if not r["paid"]]
    multisend_list = []
    for ref in unpaid:
        multisend_list.append({"wallet": ref["referrer"], "amount": 5})
        multisend_list.append({"wallet": ref["referee"], "amount": 5})

    return jsonify({
        "total_people": len(multisend_list),
        "total_ommv_to_send": sum(item["amount"] for item in multisend_list),
        "multisend_list": multisend_list
    }), 200

@app.route("/api/mark-paid", methods=["POST"])
def mark_paid():
    secret_key = request.headers.get("X-Secret-Key")
    if secret_key != SECRET_KEY:
        return jsonify({"error": "Não autorizado"}), 401

    db = load_data()
    for ref in db["referrals"]:
        ref["paid"] = True

    db["paid_referrals"] = db["referrals"]
    db["referrals"] = []

    save_data(db)
    return jsonify({"message": "Todas as indicações foram marcadas como pagas."}), 200

@app.route("/")
def index():
    return jsonify({"status": "Backend rodando"}), 200

# ========================
# Iniciar Servidor
# ========================

if __name__ == "__main__":
    from datetime import datetime
    import threading

    # Inicia thread de backup
    backup_thread = threading.Thread(target=start_backup_scheduler, daemon=True)
    backup_thread.start()

    # Iniciar servidor Flask
    app.run(host="0.0.0.0", port=PORT)
