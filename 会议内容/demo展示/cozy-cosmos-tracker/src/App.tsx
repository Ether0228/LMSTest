import { useEffect, useState } from 'react';
import { Scene } from './components/Canvas/Scene';
import { LeftPanel } from './components/HUD/LeftPanel';
import { RightPanel } from './components/HUD/RightPanel';
import { Timeline } from './components/HUD/Timeline';
import { PlanetWalk } from './components/HUD/PlanetWalk';
import { demoPhases } from './store/phaseModel';

export default function App() {
  const [phaseIndex, setPhaseIndex] = useState(0);
  const currentPhase = demoPhases[phaseIndex];

  useEffect(() => {
    const timer = setInterval(() => {
      setPhaseIndex((prev) => (prev + 1) % demoPhases.length);
    }, 9000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-[#0B0D14] text-slate-200 font-sans selection:bg-indigo-500/30 flex flex-col">
      {/* Layer 0: The Void Canvas (Top 66%) */}
      <div className="relative w-full h-[66vh]">
        <Scene phase={currentPhase} />
      </div>

      {/* Layer 0.5: The Planet Surface (Bottom 34%) */}
      <PlanetWalk phase={currentPhase} />

      {/* HUD Layers */}
      <div className="absolute inset-0 pointer-events-none z-10">
        {/* Layer 1: Left Archive */}
        <LeftPanel phase={currentPhase} />
        
        {/* Layer 2: Right Navigator */}
        <RightPanel phase={currentPhase} />
        
        {/* Layer 3: Expedition Timeline */}
        <Timeline
          phase={currentPhase}
          onSelectPhase={(id) => {
            setPhaseIndex(demoPhases.findIndex((item) => item.id === id));
          }}
        />
        
        {/* Subtle vignette overlay for extra depth */}
        <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(circle_at_center,transparent_0%,rgba(11,13,20,0.8)_100%)]"></div>
      </div>
    </div>
  );
}
