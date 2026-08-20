document.addEventListener('DOMContentLoaded', () => {
    const slides = document.querySelectorAll('.slide');
    const dots = document.querySelectorAll('.dot');
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    
    let currentSlide = 0;
    const totalSlides = slides.length;

    // --- Navigation Logic ---

    function updateSlides() {
        // Hide all slides
        slides.forEach(slide => slide.classList.remove('active'));
        dots.forEach(dot => dot.classList.remove('active'));
        
        // Show current slide
        slides[currentSlide].classList.add('active');
        dots[currentSlide].classList.add('active');

        // Update buttons state
        prevBtn.disabled = currentSlide === 0;
        nextBtn.disabled = currentSlide === totalSlides - 1;
    }

    function nextSlide() {
        if (currentSlide < totalSlides - 1) {
            currentSlide++;
            updateSlides();
        }
    }

    function prevSlide() {
        if (currentSlide > 0) {
            currentSlide--;
            updateSlides();
        }
    }

    nextBtn.addEventListener('click', nextSlide);
    prevBtn.addEventListener('click', prevSlide);

    // Keyboard navigation
    document.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowRight' || e.key === ' ') {
            nextSlide();
        } else if (e.key === 'ArrowLeft') {
            prevSlide();
        }
    });

    // --- Interactive Disparity Demo (Slide 3) ---
    const depthSlider = document.getElementById('depth-slider');
    const objRight = document.getElementById('obj-right');
    const dispVal = document.getElementById('disp-val');
    const distVal = document.getElementById('dist-val');

    // Simulate constants
    const focalLength = 800; // px
    const baseline = 0.1; // meters

    function updateInteractive() {
        const sliderValue = parseFloat(depthSlider.value); // 1 to 100
        
        // Let's map slider value to distance (Z)
        // slider=1 -> very far (e.g. 20m)
        // slider=100 -> very close (e.g. 1m)
        const maxDist = 20;
        const minDist = 1;
        // Inverse relationship to make slider feel natural (right = closer)
        const currentDist = maxDist - ((sliderValue / 100) * (maxDist - minDist));
        
        // Calculate disparity D = (F * B) / Z
        let disparity = (focalLength * baseline) / currentDist;
        
        // We limit disparity visual movement to prevent going out of bounds
        // Base center is 50%, we subtract px to move it left relative to right camera viewport
        const baseOffset = 50; 
        // Convert disparity value to a visual percentage or pixels (roughly)
        const visualDisparityOffset = Math.min(disparity, 40); 
        
        objRight.style.left = `calc(50% - ${visualDisparityOffset}px)`;
        
        // Update stats
        dispVal.textContent = `${Math.round(disparity)}px`;
        distVal.textContent = `${currentDist.toFixed(1)}m`;
        
        // Dynamic colors: closer = red/warmer (like our depth map)
        if (currentDist < 3) {
            dispVal.style.color = '#f43f5e';
            distVal.style.color = '#f43f5e';
        } else if (currentDist < 8) {
            dispVal.style.color = '#eab308';
            distVal.style.color = '#eab308';
        } else {
            dispVal.style.color = '#3b82f6';
            distVal.style.color = '#3b82f6';
        }
    }

    depthSlider.addEventListener('input', updateInteractive);
    
    // Initial call to set correct values
    updateInteractive();

    // --- Triangulation Animation Logic (Slide 5) ---
    let animStep = 0;
    const bigTri = document.getElementById('anim-big-tri');
    const small1 = document.getElementById('anim-small-1');
    const small2 = document.getElementById('anim-small-2');
    const btnAnimate = document.getElementById('btn-animate');

    if(btnAnimate) {
        btnAnimate.addEventListener('click', () => {
            if(animStep === 0) {
                // Step 1: Resaltar Triángulo Grande (Z y Baseline)
                bigTri.setAttribute('fill', 'rgba(59, 130, 246, 0.3)');
                bigTri.setAttribute('stroke-width', '2');
                btnAnimate.textContent = 'Ver Triángulos Interiores ▶ (1/5)';
                animStep++;
            } else if(animStep === 1) {
                // Step 2: Resaltar Triángulos Pequeños (x1 y x2)
                small1.setAttribute('fill', 'rgba(234, 179, 8, 0.5)');
                small1.setAttribute('stroke-width', '2');
                small2.setAttribute('fill', 'rgba(234, 179, 8, 0.5)');
                small2.setAttribute('stroke-width', '2');
                btnAnimate.textContent = 'Combinar Desplazamientos ▶ (2/5)';
                animStep++;
            } else if(animStep === 2) {
                // Step 3: Unir triángulos pequeños en el centro para formar Disparidad (D)
                // small1: +100x -> apex 200,180
                small1.setAttribute('points', '200,180 200,250 180,250');
                // small2: -100x -> apex 200,180
                small2.setAttribute('points', '200,180 200,250 280,250');
                btnAnimate.textContent = 'Mover al Objeto P ▶ (3/5)';
                animStep++;
            } else if(animStep === 3) {
                // Step 4: Trasladar al centro del triángulo grande
                // Centro del triángulo grande (Bounding Box): x=200, y=110.
                // Movemos el triángulo chico para que su centro quede exactamente ahí:
                small1.setAttribute('points', '170,75 170,145 150,145');
                small2.setAttribute('points', '170,75 170,145 250,145');
                btnAnimate.textContent = 'Demostrar Semejanza (Escalar) ▶ (4/5)';
                animStep++;
            } else if(animStep === 4) {
                // Step 5: Escalar al tamaño del triángulo grande para demostrar superposición perfecta
                // Multiplicamos tamaño base x2 desde el vértice (140,40)
                small1.setAttribute('points', '140,40 140,180 100,180');
                small2.setAttribute('points', '140,40 140,180 300,180');
                
                // Cambiamos a color verde éxito
                setTimeout(() => {
                    small1.setAttribute('fill', 'rgba(16, 185, 129, 0.6)');
                    small2.setAttribute('fill', 'rgba(16, 185, 129, 0.6)');
                    small1.setAttribute('stroke', '#10b981');
                    small2.setAttribute('stroke', '#10b981');
                    bigTri.setAttribute('fill', 'rgba(16, 185, 129, 0.3)');
                    bigTri.setAttribute('stroke', '#10b981');
                }, 800);
                
                btnAnimate.textContent = '¡Triángulos Semejantes! (Demostrado)';
                btnAnimate.disabled = true;
                btnAnimate.style.borderColor = '#10b981';
                btnAnimate.style.color = '#10b981';
                animStep++;
            }
        });
    }

    // --- Math Animation Logic (Slide 6) ---
    let mathStep = 0;
    const valD = document.getElementById('anim-val-D');
    const valF = document.getElementById('anim-val-F');
    const valB = document.getElementById('anim-val-B');
    const valZ = document.getElementById('anim-val-Z');
    const eqDiv = document.getElementById('anim-eq-div');
    const eqRes = document.getElementById('anim-eq-res');
    const btnMath = document.getElementById('btn-math');

    if(btnMath) {
        btnMath.addEventListener('click', () => {
            if(mathStep === 0) {
                // Step 1: Bases float to center to form fraction
                valB.textContent = '200';
                valB.setAttribute('x', '400');
                valB.setAttribute('y', '240');
                
                valD.textContent = '100';
                valD.setAttribute('x', '400');
                valD.setAttribute('y', '300');
                
                eqDiv.setAttribute('opacity', '1');
                
                btnMath.textContent = '▶ 2. Calcular Proporción';
                mathStep++;
            } else if(mathStep === 1) {
                // Step 2: Fraction becomes = 2
                valB.setAttribute('opacity', '0');
                valD.setAttribute('opacity', '0');
                eqDiv.setAttribute('opacity', '0');
                
                setTimeout(() => {
                    eqRes.textContent = 'Escala = 2x';
                    eqRes.setAttribute('opacity', '1');
                }, 500);
                
                btnMath.textContent = '▶ 3. Aplicar a la Altura (F)';
                mathStep++;
            } else if(mathStep === 2) {
                // Step 3: F floats to center and multiplies
                valF.textContent = '70';
                valF.setAttribute('x', '330');
                valF.setAttribute('y', '265');
                
                eqRes.textContent = '× 2';
                eqRes.setAttribute('x', '430');
                
                btnMath.textContent = '▶ 4. Resolver';
                mathStep++;
            } else if(mathStep === 3) {
                // Step 4: Resolve to 140
                valF.setAttribute('opacity', '0');
                eqRes.setAttribute('opacity', '0');
                
                setTimeout(() => {
                    eqRes.textContent = '140';
                    eqRes.setAttribute('x', '400');
                    eqRes.setAttribute('fill', '#f43f5e');
                    eqRes.setAttribute('font-size', '35');
                    eqRes.setAttribute('opacity', '1');
                }, 500);
                
                btnMath.textContent = '▶ 5. Mapear a la Realidad';
                mathStep++;
            } else if(mathStep === 4) {
                // Step 5: 140 moves to Z
                eqRes.setAttribute('x', '500');
                eqRes.setAttribute('y', '120');
                eqRes.setAttribute('font-size', '24');
                
                valZ.setAttribute('opacity', '0');
                
                setTimeout(() => {
                    eqRes.textContent = 'Z = 140 cm';
                    eqRes.setAttribute('x', '550'); // adjust center to fit text
                }, 1000);
                
                btnMath.textContent = '¡Cálculo Demostrado!';
                btnMath.disabled = true;
                btnMath.style.borderColor = '#10b981';
                btnMath.style.color = '#10b981';
                mathStep++;
            }
        });
    }
});
