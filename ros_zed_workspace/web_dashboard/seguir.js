// Modo seguimiento (RF-10): dibuja las personas que publica person_follower.py
// sobre la imagen de la camara y manda el ID elegido con un clic.
const canvas = document.getElementById('cameraCanvas');
const ctx = canvas.getContext('2d');
const listEl = document.getElementById('personList');
const statusEl = document.getElementById('followStatus');
const statusText = document.getElementById('ros-status-text');
const statusDot = document.getElementById('ros-status-dot');

let persons = [];      // [{id, dist, bbox:[x0,y0,x1,y1] normalizados}]
let targetId = null;
let frame = null;      // ultima imagen RGB cargada

const ros = new ROSLIB.Ros({ url: 'ws://' + window.location.hostname + ':9090' });
ros.on('connection', () => {
    statusText.innerText = 'CONECTADO AL NÚCLEO ROS';
    statusDot.style.backgroundColor = 'var(--primary-neon)';
});
ros.on('error', () => { statusText.innerText = 'SIN CONEXIÓN CON ROS'; statusDot.style.backgroundColor = '#f43f5e'; });
ros.on('close', () => { statusText.innerText = 'SIN CONEXIÓN CON ROS'; statusDot.style.backgroundColor = '#f43f5e'; });

const targetTopic = new ROSLIB.Topic({ ros, name: '/person_follow/target_id', messageType: 'std_msgs/Int32' });

new ROSLIB.Topic({ ros, name: '/person_follow/detections', messageType: 'std_msgs/String', throttle_rate: 100 })
    .subscribe(msg => {
        const data = JSON.parse(msg.data);
        persons = data.persons;
        targetId = data.target_id;
        renderList();
    });

new ROSLIB.Topic({ ros, name: '/person_follow/status', messageType: 'std_msgs/String' })
    .subscribe(msg => {
        statusEl.innerText = msg.data;
        statusEl.className = msg.data === 'objetivo perdido' ? 'lost' : (msg.data === 'siguiendo' ? 'following' : '');
    });

function follow(id) {
    targetTopic.publish({ data: id });
    targetId = id >= 0 ? id : null;
    renderList();
}

document.getElementById('stopBtn').addEventListener('click', () => follow(-1));

// Clic sobre la imagen: elige la persona cuyo recuadro contiene el punto
// (si hay varias superpuestas, la mas cercana a la camara).
canvas.addEventListener('click', ev => {
    const r = canvas.getBoundingClientRect();
    const u = (ev.clientX - r.left) / r.width;
    const v = (ev.clientY - r.top) / r.height;
    const hits = persons.filter(p => u >= p.bbox[0] && u <= p.bbox[2] && v >= p.bbox[1] && v <= p.bbox[3]);
    if (hits.length) {
        hits.sort((a, b) => (a.dist ?? 0) - (b.dist ?? 0));  // sin distancia = muy cerca
        follow(hits[0].id);
    }
});

// dist null = la ZED no dio profundidad valida (mas cerca de 0,3 m).
const fmtDist = d => (d === null || d === undefined) ? '< 0,3 m' : `${d.toFixed(1)} m`;

function renderList() {
    listEl.innerHTML = '';
    if (!persons.length) {
        listEl.innerHTML = '<li>No se detectan personas</li>';
        return;
    }
    for (const p of persons) {
        const li = document.createElement('li');
        if (p.id === targetId) li.className = 'target';
        li.innerHTML = `<span>Persona ${p.id} · ${fmtDist(p.dist)}</span>`;
        const btn = document.createElement('button');
        btn.className = 'follow-btn';
        btn.innerText = p.id === targetId ? 'SIGUIENDO' : 'SEGUIR';
        btn.addEventListener('click', () => follow(p.id));
        li.appendChild(btn);
        listEl.appendChild(li);
    }
}

function draw() {
    const W = canvas.width, H = canvas.height;
    if (frame) {
        ctx.drawImage(frame, 0, 0, W, H);
    } else {
        ctx.fillStyle = '#02040a';
        ctx.fillRect(0, 0, W, H);
        ctx.fillStyle = '#2dd4bf';
        ctx.font = '28px Orbitron';
        ctx.textAlign = 'center';
        ctx.fillText('ESPERANDO IMAGEN DE LA CÁMARA...', W / 2, H / 2);
    }
    for (const p of persons) {
        const [x0, y0, x1, y1] = p.bbox;
        const isTarget = p.id === targetId;
        ctx.strokeStyle = isTarget ? '#facc15' : '#2dd4bf';
        ctx.lineWidth = isTarget ? 6 : 3;
        ctx.strokeRect(x0 * W, y0 * H, (x1 - x0) * W, (y1 - y0) * H);
        const label = `#${p.id}  ${fmtDist(p.dist)}${isTarget ? '  ◀ OBJETIVO' : ''}`;
        ctx.font = 'bold 26px Inter';
        ctx.textAlign = 'left';
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = isTarget ? '#facc15' : '#2dd4bf';
        ctx.fillRect(x0 * W, Math.max(0, y0 * H - 34), tw + 16, 34);
        ctx.fillStyle = '#02040a';
        ctx.fillText(label, x0 * W + 8, Math.max(26, y0 * H - 8));
    }
}

// rgb.jpg lo escribe depth_to_heatmap.py; se recarga a ~5 fps como el heatmap del panel principal.
setInterval(() => {
    const img = new Image();
    img.onload = () => { frame = img; };
    img.src = 'rgb.jpg?rand=' + Math.random();
}, 200);
setInterval(draw, 100);
renderList();
