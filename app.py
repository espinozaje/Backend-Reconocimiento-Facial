from flask import Flask, request, jsonify, send_from_directory
import os, json, cv2
import numpy as np
from base64 import b64decode
from datetime import datetime
from twilio.rest import Client
import mysql.connector
from PIL import Image
from keras_facenet import FaceNet

app = Flask(__name__)
os.makedirs("imagenes", exist_ok=True)

# --- Inicializar FaceNet ---
embedder = FaceNet()
print("HOST:", os.getenv("MYSQLHOST"))
print("user:", os.getenv("MYSQLUSER"))
print("pass:", os.getenv("MYSQLPASSWORD"))
print("db:", os.getenv("MYSQLDATABASE"))
print("port:", os.getenv("MYSQLPORT"))
@app.route('/imagenes/<path:filename>')
def servir_imagen(filename):
    return send_from_directory('imagenes', filename)

# --- Twilio SMS ---
def enviar_sms_alerta(numero_destino, mensaje):
    account_sid = 'ACdf4f31bbd04400119b690f6c7c09f53a'
    auth_token = '442b9e403d9cb25c710d508302aee8f8'
    client = Client(account_sid, auth_token)
    message = client.messages.create(body=mensaje, from_='+16282824764', to=numero_destino)
    print("Mensaje enviado con SID:", message.sid)

# --- Conexión MySQL ---
def conectar_bd():
    return mysql.connector.connect(
        host=os.getenv("MYSQLHOST"),
        user=os.getenv("MYSQLUSER"),
        password=os.getenv("MYSQLPASSWORD"),
        database=os.getenv("MYSQLDATABASE"),
        port=int(os.getenv("MYSQLPORT", 3306))  # asegúrate que sea int
    )

# --- Crear tabla si no existe ---
def inicializar_tabla():
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(100),
        apellido VARCHAR(100),
        codigo VARCHAR(50) UNIQUE,
        email VARCHAR(100),
        requisitoriado BOOLEAN,
        direccion VARCHAR(255),
        imagen VARCHAR(255),
        embedding JSON,
        fecha DATETIME
    )""")
    conn.commit()
    cursor.close()
    conn.close()

inicializar_tabla()

# --- Función para extraer embedding ---
def extraer_embedding(img_bgr):
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    faces = embedder.extract(img_rgb, threshold=0.95)
    if len(faces) > 0:
        return faces[0]['embedding']
    return None

# --- Cálculo manual de similitud del coseno ---
def similitud_coseno_manual(vec1, vec2):
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5
    return dot / (norm1 * norm2) if norm1 > 0 and norm2 > 0 else 0

# --- Registro de usuario ---
@app.route('/registro', methods=['POST'])
def registro():
    data = request.json
    image_data = b64decode(data['imagen'].split(',')[1])
    nparr = np.frombuffer(image_data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    embedding = extraer_embedding(img)
    if embedding is None:
        return jsonify({"status": "error", "mensaje": "No se detectó rostro"})

    nombre = data['nombre'].strip()
    apellido = data['apellido'].strip()
    codigo = data['codigo']
    email = data['email']
    direccion = data['direccion']
    requisitoriado = data['requisitoriado']

    # Carpeta y nombre del archivo
    carpeta_usuario = os.path.join("imagenes", f"{nombre}_{apellido}")
    os.makedirs(carpeta_usuario, exist_ok=True)
    filename = f"{codigo}_{datetime.now().timestamp()}.jpg"
    ruta_local = os.path.join(carpeta_usuario, filename)


    cv2.imwrite(ruta_local, img)


    ruta_imagen_relativa = f"imagenes/{nombre}_{apellido}/{filename}"

    try:
        conn = conectar_bd()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO usuarios (nombre, apellido, codigo, email, requisitoriado, direccion, imagen, embedding, fecha)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (nombre, apellido, codigo, email, requisitoriado, direccion, ruta_imagen_relativa, json.dumps(embedding.tolist()), datetime.now()))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "ok", "mensaje": "Usuario registrado exitosamente"})
    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)})


# --- Verificación ---
@app.route('/verificar', methods=['POST'])
def verificar():
    data = request.json
    image_data = b64decode(data['imagen'].split(',')[1])
    nparr = np.frombuffer(image_data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    embedding_input = extraer_embedding(img)
    if embedding_input is None:
        return jsonify({"status": "error", "mensaje": "No se detectó rostro"})

    conn = conectar_bd()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM usuarios")
    usuarios = cursor.fetchall()
    cursor.close()
    conn.close()

    mejor_sim = 0
    mejor_usuario = None
    for user in usuarios:
        emb = json.loads(user['embedding'])
        sim = similitud_coseno_manual(embedding_input, emb)
        if sim > mejor_sim:
            mejor_sim = sim
            mejor_usuario = user

    if mejor_usuario and mejor_sim > 0.6:
        if mejor_usuario['requisitoriado']:
            enviar_sms_alerta(
                '+51952272635',
                f"🚨 ALERTA REQUISITORIADO 🚨\n"
                        f"Nombre: {mejor_usuario['nombre']} {mejor_usuario['apellido']}\n"
                        f"Código: {mejor_usuario['codigo']}\n"
                        f"Email: {mejor_usuario['email']}\n"
                        f"Dirección: {mejor_usuario['direccion']}\n"
                        f"Similitud: {round(mejor_sim, 2)}"
            )
            return jsonify({
                "status": "alerta",
                "mensaje": f"¡ALERTA! {mejor_usuario['nombre']} {mejor_usuario['apellido']} es requisitoriado",
                "usuario": {
                    "id": mejor_usuario['id'],
                    "nombre": mejor_usuario['nombre'],
                    "apellido": mejor_usuario['apellido'],
                    "codigo": mejor_usuario['codigo'],
                    "email": mejor_usuario['email'],
                    "direccion": mejor_usuario['direccion'],
                    "requisitoriado": mejor_usuario['requisitoriado'],
                    "imagen": mejor_usuario['imagen'].replace("\\", "/"),
                    "similitud": round(mejor_sim, 2)
                }
            })
        else:
            return jsonify({
                "status": "ok",
                "mensaje": "Reconocido",
                "usuario": {
                    "id": mejor_usuario['id'],
                    "nombre": mejor_usuario['nombre'],
                    "apellido": mejor_usuario['apellido'],
                    "codigo": mejor_usuario['codigo'],
                    "email": mejor_usuario['email'],
                    "direccion": mejor_usuario['direccion'],
                    "requisitoriado": mejor_usuario['requisitoriado'],
                    "imagen": mejor_usuario['imagen'].replace("\\", "/"),
                    "similitud": round(mejor_sim, 2)
                }
            })
    else:
        return jsonify({
            "status": "ok",
            "mensaje": f"No reconocido ({round(mejor_sim, 2)})"
        })
    
# --- CRUD Usuarios ---
@app.route('/usuarios', methods=['GET'])
def listar_usuarios():
    try:
        conn = conectar_bd()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM usuarios")
        usuarios = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(usuarios)
    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)})

@app.route('/usuario/<int:uid>', methods=['PUT'])
def actualizar_usuario(uid):
    data = request.json
    campos = ["nombre", "apellido", "codigo", "email", "requisitoriado", "direccion"]
    valores = [data[c] for c in campos]
    consulta = ", ".join([f"{c} = %s" for c in campos])
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute(f"UPDATE usuarios SET {consulta} WHERE id = %s", (*valores, uid))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"status": "ok", "mensaje": "Usuario actualizado"})

@app.route('/usuario/<int:uid>', methods=['DELETE'])
def eliminar_usuario(uid):
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM usuarios WHERE id = %s", (uid,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"status": "ok", "mensaje": "Usuario eliminado"})

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
