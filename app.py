from flask import Flask, request, jsonify, send_from_directory
import os, json, cv2
import numpy as np
from base64 import b64decode
from datetime import datetime
from twilio.rest import Client
import mysql.connector
from PIL import Image
from keras_facenet import FaceNet
from google.cloud import storage
app = Flask(__name__)
os.makedirs("imagenes", exist_ok=True)

# --- Inicializar FaceNet ---
embedder = FaceNet()

# --- Google Cloud Storage ---
def subir_a_cloud_storage(ruta_local, destino_bucket):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credenciales.json"
    client = storage.Client()
    bucket = client.bucket("bucket-reconocimiento")
    blob = bucket.blob(destino_bucket)
    blob.upload_from_filename(ruta_local)

    return f"https://storage.googleapis.com/{bucket.name}/{blob.name}"

@app.route('/imagenes/<path:filename>')
def servir_imagen(filename):
    return send_from_directory('imagenes', filename)

# --- Twilio SMS ---
def enviar_sms_alerta(numero_destino, mensaje):
    account_sid = os.getenv('TWILIO_SID')
    auth_token = os.getenv('TWILIO_AUTH')
    client = Client(account_sid, auth_token)
    message = client.messages.create(body=mensaje, from_='+16282824764', to=numero_destino)
    print("Mensaje enviado con SID:", message.sid)

# --- Conexión MySQL ---
def conectar_bd():
    try:
        conn = mysql.connector.connect(
           host='35.224.213.115',
           user='admin',
           password='R9R%YfKO"yQmg?9j',
           database='reconocimiento'
        )
        print("Conexión exitosa a la base de datos")
        return conn
    except mysql.connector.Error as err:
        print(f"Error al conectar a la base de datos: {err}")
        return None

def inicializar_tabla():
    conn = conectar_bd()
    if conn is None:
        return
    try:
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
        print("Tabla 'usuarios' creada o ya existente")
    except mysql.connector.Error as err:
        print(f"Error al crear la tabla: {err}")
    finally:
        cursor.close()
        conn.close()

print(f"Directorio actual: {os.getcwd()}")
print("Ejecutando inicialización de tabla...")
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

    filename = f"{codigo}_{datetime.now().timestamp()}.jpg"
    carpeta_usuario = f"{nombre}_{apellido}"
    ruta_local = os.path.join("imagenes", carpeta_usuario, filename)
    os.makedirs(os.path.dirname(ruta_local), exist_ok=True)
    cv2.imwrite(ruta_local, img)

    url_imagen = subir_a_cloud_storage(ruta_local, f"{carpeta_usuario}/{filename}")

    try:
        conn = conectar_bd()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO usuarios (nombre, apellido, codigo, email, requisitoriado, direccion, imagen, embedding, fecha)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (nombre, apellido, codigo, email, requisitoriado, direccion, url_imagen, json.dumps(embedding.tolist()), datetime.now()))
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

    actualizar_foto = 'imagen' in data

    if actualizar_foto:
        image_data = b64decode(data['imagen'].split(',')[1])
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        embedding = extraer_embedding(img)

        if embedding is None:
            return jsonify({"status": "error", "mensaje": "No se detectó rostro"})

        nombre, apellido, codigo = data["nombre"], data["apellido"], data["codigo"]
        filename = f"{codigo}_{datetime.now().timestamp()}.jpg"
        carpeta_usuario = f"{nombre}_{apellido}"
        ruta_local = os.path.join("imagenes", carpeta_usuario, filename)
        os.makedirs(os.path.dirname(ruta_local), exist_ok=True)
        cv2.imwrite(ruta_local, img)

        url_imagen = subir_a_cloud_storage(ruta_local, f"{carpeta_usuario}/{filename}")

        campos += ["imagen", "embedding"]
        valores += [url_imagen, json.dumps(embedding.tolist())]

    consulta = ", ".join([f"{c} = %s" for c in campos])
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute(f"UPDATE usuarios SET {consulta} WHERE id = %s", (*valores, uid))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"status": "ok", "mensaje": "Usuario actualizado con foto" if actualizar_foto else "Usuario actualizado"})


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
