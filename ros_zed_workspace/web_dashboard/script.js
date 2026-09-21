// Update Clock
function updateClock() {
    const now = new Date();
    document.getElementById('clock').innerText = now.toLocaleTimeString('en-US', { hour12: false });
}
setInterval(updateClock, 1000);
updateClock();

// Panel "MAPA 2D + RUTA": refresca la imagen generada por render_plan.py (costmap + plan de move_base)
const planImg = document.getElementById('planImg');
setInterval(() => {
    planImg.src = 'plan_demo.png?rand=' + Math.random();
}, 1000);

// UI Elements
const statusText = document.getElementById('ros-status-text');
const statusDot = document.getElementById('ros-status-dot');
const velLinearEl = document.getElementById('vel-linear');
const velLinearBar = document.getElementById('vel-linear-bar');
const velAngularEl = document.getElementById('vel-angular');
const steeringWheel = document.getElementById('steering-wheel');
const canvas = document.getElementById('costmapCanvas');
const ctx = canvas.getContext('2d');

// Canvas dimensions
const WIDTH = canvas.width;
const HEIGHT = canvas.height;
const CELL_SIZE = 10;
const COLS = Math.floor(WIDTH / CELL_SIZE);
const ROWS = Math.floor(HEIGHT / CELL_SIZE);

// ROS Connection setup (rosbridge_websocket usually runs on port 9090)
const ros = new ROSLIB.Ros({
    url : 'ws://' + window.location.hostname + ':9090'
});

ros.on('connection', function() {
    console.log('Connected to websocket server.');
    statusText.innerText = "CONECTADO AL NÚCLEO ROS";
    statusDot.classList.add('connected');
    statusDot.style.backgroundColor = 'var(--primary-neon)';
    statusDot.style.boxShadow = '0 0 10px var(--primary-neon)';
});

ros.on('error', function(error) {
    console.log('Error connecting to websocket server: ', error);
    startSimulationMode(); // Fallback
});

ros.on('close', function() {
    console.log('Connection to websocket server closed.');
    startSimulationMode(); // Fallback
});

// ROS Subscribers
const cmdVelListener = new ROSLIB.Topic({
    ros : ros,
    name : '/cmd_vel',
    messageType : 'geometry_msgs/Twist'
});

cmdVelListener.subscribe(function(message) {
    updateTelemetry(message.linear.x, message.angular.z);
});

// Suscripción al Mapa de Calor (Costmap 2D para IA, no se dibuja directamente ahora)
const costmapListener = new ROSLIB.Topic({
    ros : ros,
    name : '/move_base/local_costmap/costmap',
    messageType : 'nav_msgs/OccupancyGrid'
});

// Mapa de calor coloreado (generado por depth_to_heatmap.py a partir de /zed/zed_node/depth/depth_registered)
const heatmapUrl = 'heatmap.jpg';

// Bucle para dibujar el heatmap en el canvas, siempre actualizado (no depende del estado de rosbridge)
setInterval(() => {
    const img = new Image();
    img.src = heatmapUrl + '?rand=' + Math.random();

    img.onload = function() {
        ctx.drawImage(img, 0, 0, WIDTH, HEIGHT);

        // Dibujar la cruz del centro (HUD)
        ctx.strokeStyle = 'rgba(45, 212, 191, 0.5)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(WIDTH/2, 0);
        ctx.lineTo(WIDTH/2, HEIGHT);
        ctx.moveTo(0, HEIGHT/2);
        ctx.lineTo(WIDTH, HEIGHT/2);
        ctx.stroke();
    };

    img.onerror = function() {
        ctx.fillStyle = '#02040a';
        ctx.fillRect(0, 0, WIDTH, HEIGHT);
        ctx.fillStyle = '#2dd4bf';
        ctx.font = '20px Orbitron';
        ctx.textAlign = 'center';
        ctx.fillText('ESPERANDO HEATMAP...', WIDTH/2, HEIGHT/2);
    };
}, 100); // 10 FPS

let simInterval = null;

function updateTelemetry(linear, angular) {
    // Update text
    velLinearEl.innerText = linear.toFixed(2);
    velAngularEl.innerText = angular.toFixed(2);
    
    // Update progress bar (assuming max speed is 1.5 m/s)
    let percent = Math.min(Math.max((linear / 1.5) * 100, 0), 100);
    velLinearBar.style.width = percent + '%';
    
    // Update steering wheel rotation (assuming max steering is 1.0 rad/s)
    let deg = Math.min(Math.max(angular * 90, -90), 90);
    steeringWheel.style.transform = `rotate(${deg}deg)`;
}

function drawSimulatedCostmap(targetAngular) {
    const img = new Image();
    img.src = 'heatmap.jpg?rand=' + Math.random(); // Evitar caché
    
    img.onload = function() {
        // Dibujar el mapa real de la cámara ZED
        ctx.drawImage(img, 0, 0, WIDTH, HEIGHT);
    };
    
    img.onerror = function() {
        // Fallback original: Simulación si el mapa no está
        ctx.fillStyle = '#02040a';
        ctx.fillRect(0, 0, WIDTH, HEIGHT);
        const time = Date.now() * 0.002;
        for (let r = 0; r < ROWS; r++) {
            for (let c = 0; c < COLS; c++) {
                const corridorCenter = COLS/2 + Math.sin(time - r*0.1) * (COLS/4);
                const distFromCenter = Math.abs(c - corridorCenter);
                if (distFromCenter > 15) {
                    ctx.fillStyle = '#f43f5e'; 
                    ctx.fillRect(c * CELL_SIZE, r * CELL_SIZE, CELL_SIZE-1, CELL_SIZE-1);
                } else if (distFromCenter > 12) {
                    ctx.fillStyle = 'rgba(129, 140, 248, 0.6)';
                    ctx.fillRect(c * CELL_SIZE, r * CELL_SIZE, CELL_SIZE-1, CELL_SIZE-1);
                }
            }
        }
    };
}

function startSimulationMode() {
    if (simInterval) return;
    
    statusText.innerText = "ESPERANDO CONEXIÓN ROS... (MODO SIMULACIÓN)";
    statusDot.classList.remove('connected');
    statusDot.style.backgroundColor = '#eab308'; // Yellow
    statusDot.style.boxShadow = '0 0 10px #eab308';
    
    let targetAngular = 0;
    let currentAngular = 0;
    
    simInterval = setInterval(() => {
        const time = Date.now() * 0.002;
        // Calculate the ideal steering to follow the simulated corridor
        // The corridor center at the bottom (r=ROWS) dictates steering
        const bottomCorridorCenter = COLS/2 + Math.sin(time - ROWS*0.1) * (COLS/4);
        const error = (COLS/2 - bottomCorridorCenter) / (COLS/2);
        
        targetAngular = error * 1.5; // rad/s
        currentAngular += (targetAngular - currentAngular) * 0.1; // Smooth steering
        
        const linear = 0.5 + Math.random() * 0.1; // roughly 0.5 m/s
        
        updateTelemetry(linear, currentAngular);
        drawSimulatedCostmap(currentAngular);
        
    }, 100); // 10 FPS
}
