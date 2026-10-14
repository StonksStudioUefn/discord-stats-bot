/* ═════════════ STONKS · la chispa ═════════════ */
/* El logo de las apps: doce rayos de largo desigual, como la chispa de Claude.
   Script clásico sin dependencias ni `export`: sirve con un <script src> en
   cualquier página y también pegado dentro de un <script type="module"> (el
   kanban lo junta así con su build). Por eso todo lo que no es de uso
   público empieza por CHISPA_ o chispa_, para no chocar con el código de la
   app que comparte ámbito. */
const CHISPA_LARGOS=[46,37,43,34,47,39,42,35,45,38,44,36];
const CHISPA_DESVIO=[0,4,-3,2,-4,3,-2,5,-3,2,-5,3];
const chispa_rayo=L=>`M-6.2 -8 L-2.9 ${-L+3.2} Q0 ${-L-1.6} 2.9 ${-L+3.2} L6.2 -8 Z`;
/* El color acaba en un atributo: solo se acepta lo que parece un color o un
   var(--algo), nunca comillas ni ángulos. */
const chispa_color=c=>/^[#\w\s(),.%-]+$/.test(String(c||''))?String(c):'currentColor';
const chispa_quieto=()=>typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches;
function chispa_svg(color,escala,extra=''){
  const rayos=CHISPA_LARGOS.map((L,i)=>`<path d="${chispa_rayo(L)}" transform="rotate(${i*30+CHISPA_DESVIO[i]})${escala}"/>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-50 -50 100 100"${extra}><g style="fill:${chispa_color(color)}">${rayos}<circle r="11"/></g></svg>`;
}

/* La chispa pequeña, para el icono de la pestaña y todo lo que vaya a menos
   de unos 24 px: a 16 px los doce rayos finos se juntan en una mancha. Nueve
   rayos más gruesos y con la punta redonda, con el mismo largo desigual y el
   mismo desvío que el logo para que se siga reconociendo (el equipo eligió 9
   entre 6, 7, 8 y 9 el 02/10/2026). El viewBox se ajusta a la forma para que llene el cuadro sin
   margen. */
const CHISPA_ICONO=(()=>{
  const largos=[50,45,49,46,50,45,48,46,49], desvio=CHISPA_DESVIO.slice(0,9), base=9.6, punta=5.1, centro=19;
  let x0=-centro,x1=centro,y0=-centro,y1=centro;
  const rayos=largos.map((L,i)=>{
    const g=i*40+desvio[i], a=g*Math.PI/180, d=L-punta, cx=Math.sin(a)*d, cy=-Math.cos(a)*d;
    x0=Math.min(x0,cx-punta); x1=Math.max(x1,cx+punta); y0=Math.min(y0,cy-punta); y1=Math.max(y1,cy+punta);
    return `<path d="M${-base} 0 L${-punta} ${-d} A${punta} ${punta} 0 0 1 ${punta} ${-d} L${base} 0 Z" transform="rotate(${g})"/>`;
  }).join('');
  const lado=Math.max(x1-x0,y1-y0), f=n=>+n.toFixed(2);
  return {rayos:rayos+`<circle r="${centro}"/>`,caja:[f((x0+x1-lado)/2),f((y0+y1-lado)/2),f(lado),f(lado)].join(' ')};
})();
function chispa_icono(color,extra=''){
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${CHISPA_ICONO.caja}"${extra}><g style="fill:${chispa_color(color)}">${CHISPA_ICONO.rayos}</g></svg>`;
}

/* La chispa quieta, como texto SVG. Con `titulo` se anuncia como imagen; sin
   él es decorativa. */
function chispaSVG({color='currentColor',tam=24,titulo=''}={}){
  const t=String(titulo).replace(/[<>&"]/g,'');
  return chispa_svg(color,'',` width="${+tam||24}" height="${+tam||24}"`+(t?` role="img" aria-label="${t}"`:' aria-hidden="true"'));
}

/* La chispa pequeña quieta, como chispaSVG. */
function chispaIconoSVG({color='currentColor',tam=16,titulo=''}={}){
  const t=String(titulo).replace(/[<>&"]/g,'');
  return chispa_icono(color,` width="${+tam||16}" height="${+tam||16}"`+(t?` role="img" aria-label="${t}"`:' aria-hidden="true"'));
}

/* La chispa viva. Nace rayo a rayo y ya no se para: respira en ola y gira
   despacio; con `intensa()` a true late más fuerte y gira más rápido (el
   kanban lo usa para «el agente está trabajando»). impulso() da un acelerón,
   para el hover.
   Con prefers-reduced-motion nada gira ni cambia de tamaño: con
   reducido:'onda' (lo normal, para cargas) los rayos se encienden en ola solo
   con la opacidad, para que se siga viendo que algo pasa; con 'quieta' (un
   logo) se queda fija. `reducir` lo fuerza (la guía enseña los dos).
   Si se saca del documento deja de pintar sola; despertar() la vuelve a
   poner en marcha si se mete otra vez. */
function chispaCarga(nodo,{color='var(--accent,#F06C3E)',tam=28,etiqueta='Cargando',clase='chispa',intensa=()=>false,reducido='onda',reducir=chispa_quieto()}={}){
  const modo=reducir?reducido:'viva';
  const el=document.createElement('span');
  el.className=clase;
  /* Con tam:0 el tamaño lo pone el CSS de la app (el logo del kanban). */
  if(tam){el.style.display='inline-block'; el.style.width=el.style.height=(+tam||28)+'px'; el.style.flex='none';}
  if(etiqueta){el.setAttribute('role','status'); el.setAttribute('aria-label',etiqueta);}
  else el.setAttribute('aria-hidden','true');
  el.innerHTML=chispa_svg(color,modo==='viva'?' scale(1 0.001)':'',' style="display:block;width:100%;height:100%;overflow:visible" aria-hidden="true"');
  const g=el.querySelector('g'), rayos=[...g.querySelectorAll('path')];
  const nace=performance.now();
  let raf=0,last=0,giro=0,vgiro=0,meta=0,golpe=0,vivo=true;
  /* Sobrepasa un poco al nacer, como un muelle que llega con masa. */
  const atras=x=>{const c=1.9; return 1+(c+1)*Math.pow(x-1,3)+c*Math.pow(x-1,2);};
  const onda=ts=>rayos.forEach((r,i)=>r.style.opacity=(.35+.65*(.5+.5*Math.sin(ts/1000*2.4-i*Math.PI/6))).toFixed(3));
  const viva=(ts,dt)=>{
    const on=!!intensa(), bp=golpe?(ts-golpe)/1400:1;
    const amp=(on?.2:.08)+(bp<1?.12*Math.sin(Math.PI*bp):0);
    meta+=dt*(on?38:9);
    const k=140, c=2*.72*Math.sqrt(k);
    vgiro+=((meta-giro)*k-c*vgiro)*dt; giro+=vgiro*dt;
    rayos.forEach((r,i)=>{
      const p=Math.min(1,Math.max(0,(ts-nace-i*55)/650)), base=p<1?atras(p):1;
      const s=Math.max(.001,base*(1+amp*Math.sin(ts/1000*(on?5.5:4)-i*Math.PI/3)));
      r.setAttribute('transform',`rotate(${i*30+CHISPA_DESVIO[i]}) scale(1 ${s.toFixed(3)})`);
    });
    g.setAttribute('transform',`rotate(${giro.toFixed(2)})`);
    if(bp>=1)golpe=0;
  };
  const frame=ts=>{
    if(!el.isConnected||!vivo){raf=0; last=0; return;}
    const dt=last?Math.min((ts-last)/1000,.1):1/60; last=ts;
    if(modo==='viva')viva(ts,dt); else onda(ts);
    raf=requestAnimationFrame(frame);
  };
  const despertar=()=>{if(vivo&&modo!=='quieta'&&!raf)raf=requestAnimationFrame(frame);};
  const impulso=()=>{if(modo!=='viva')return; meta+=60; golpe=performance.now(); despertar();};
  const parar=()=>{vivo=false; cancelAnimationFrame(raf); raf=0;};
  if(nodo)nodo.append(el);
  despertar();
  return {el,despertar,impulso,parar};
}

/* El icono de la pestaña: la chispa pequeña en el color de la app. Sin color, el
   --accent que tenga la página (por eso conviene llamarla con el CSS ya
   cargado). Quita los iconos que hubiera. */
function faviconChispa(color){
  let c=color||getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()||'#F06C3E';
  if(!/^#[0-9a-f]{3,8}$/i.test(c)&&!/^rgba?\([\d\s.,%]+\)$/i.test(c))c='#F06C3E';
  const href='data:image/svg+xml,'+encodeURIComponent(chispa_icono(c,' width="64" height="64"'));
  document.querySelectorAll('link[rel~="icon"]').forEach(n=>n.remove());
  const l=document.createElement('link');
  l.rel='icon'; l.type='image/svg+xml'; l.href=href;
  document.head.append(l);
  return href;
}
