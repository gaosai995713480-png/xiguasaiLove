<template>
  <div class="aurora-layer">
    <div class="aurora-band band-1"></div>
    <div class="aurora-band band-2"></div>
    <div class="aurora-band band-3"></div>
  </div>
</template>

<style scoped>
.aurora-layer {
  position: fixed;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 1;
}

/*
 * 不用 filter: blur(80px) 做柔边：它会在每帧合成时对整条光带重新模糊，
 * 是所有主题特效里最重的一项。改用径向渐变自带柔和边缘，效果接近但零逐帧成本。
 */
.aurora-band {
  position: absolute;
  width: 200%;
  height: 50%;
  opacity: 0.3;
  will-change: transform, opacity;
}

.band-1 {
  top: -15%;
  left: -50%;
  background: radial-gradient(ellipse 50% 50% at 50% 50%, rgba(52, 211, 153, 0.45), rgba(99, 102, 241, 0.25) 45%, transparent 72%);
  animation: aurora-drift-1 12s ease-in-out infinite alternate;
}

.band-2 {
  top: 5%;
  left: -30%;
  background: radial-gradient(ellipse 50% 50% at 50% 50%, rgba(167, 139, 250, 0.4), rgba(52, 211, 153, 0.2) 45%, transparent 72%);
  animation: aurora-drift-2 16s ease-in-out infinite alternate;
}

.band-3 {
  top: -10%;
  left: -40%;
  background: radial-gradient(ellipse 50% 50% at 50% 50%, rgba(99, 102, 241, 0.35), rgba(167, 139, 250, 0.18) 45%, transparent 72%);
  animation: aurora-drift-3 20s ease-in-out infinite alternate;
}

@keyframes aurora-drift-1 {
  0% { transform: translateX(0) translateY(0) rotate(-5deg); opacity: 0.25; }
  100% { transform: translateX(25%) translateY(10%) rotate(5deg); opacity: 0.4; }
}

@keyframes aurora-drift-2 {
  0% { transform: translateX(0) translateY(0) rotate(3deg); opacity: 0.2; }
  100% { transform: translateX(-20%) translateY(-5%) rotate(-3deg); opacity: 0.35; }
}

@keyframes aurora-drift-3 {
  0% { transform: translateX(10%) translateY(5%) rotate(-2deg); opacity: 0.15; }
  100% { transform: translateX(-15%) translateY(-8%) rotate(4deg); opacity: 0.3; }
}

@media (prefers-reduced-motion: reduce) {
  .aurora-band { animation: none; }
}
</style>