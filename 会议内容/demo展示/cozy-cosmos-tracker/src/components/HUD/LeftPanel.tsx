import { motion, AnimatePresence } from 'framer-motion';
import { studentData, assignments } from '../../store/mockData';
import { User, Compass, History } from 'lucide-react';
import { useStore } from '../../store/useStore';
import type { DemoPhase } from '../../store/phaseModel';

export function LeftPanel({ phase }: { phase: DemoPhase }) {
  const memos = useStore((state) => state.memos);

  // --- Compute Exploration Degree ---
  const revealThreshold = Math.floor(assignments.length * phase.revealRatio);
  const visibleAssignments = assignments.filter((_, index) => index <= revealThreshold);
  const submittedAssignments = visibleAssignments.filter(a => a.status === 'Submitted');
  
  const explorationDegree = visibleAssignments.length > 0 
    ? Math.round((submittedAssignments.length / visibleAssignments.length) * 100)
    : 0;

  // --- Compute AoL Captured ---
  const aols = assignments.filter(a => a.type === 'AOL');
  const visibleAols = aols.filter((_, index) => assignments.indexOf(aols[index]) <= revealThreshold);
  const capturedAols = visibleAols.filter(a => a.status === 'Submitted').length;
  const totalAoLs = 6;

  // Colors based on phase/mood
  const isConfident = phase.catMood === 'confident';
  const radarColor = isConfident ? 'text-amber-400' : 'text-emerald-400';
  const radarBg = isConfident ? 'bg-amber-500' : 'bg-emerald-500';
  const ringColor = isConfident ? 'text-amber-500/80' : 'text-emerald-500/80';
  const glowShadow = isConfident ? 'drop-shadow-[0_0_12px_rgba(251,191,36,0.4)]' : 'drop-shadow-[0_0_12px_rgba(16,185,129,0.3)]';

  // SVG parameters for standard full circle progress
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (explorationDegree / 100) * circumference;

  return (
    <motion.div 
      initial={{ x: -50, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.8, ease: "easeOut" }}
      className="absolute left-8 top-8 bottom-24 w-80 z-10 flex flex-col gap-6"
    >
      {/* 1. Student Anchor */}
      <div className="backdrop-blur-md bg-white/5 border border-white/10 rounded-2xl p-5 shadow-2xl relative overflow-hidden shrink-0">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-full bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center shrink-0">
            <User className="w-6 h-6 text-indigo-400" />
          </div>
          <div>
            <h2 className="text-[10px] uppercase tracking-widest text-slate-400 font-mono mb-1">Student ID: {studentData.name}</h2>
            <h1 className="text-xs font-medium text-slate-200 leading-tight">{studentData.course}</h1>
          </div>
        </div>
      </div>

      {/* 2. Exploration Radar (Replacing Gradebook) */}
      <div className="backdrop-blur-md bg-white/5 border border-white/10 rounded-2xl p-5 shadow-2xl flex flex-col items-center shrink-0">
        <div className="w-full flex justify-between items-center mb-4">
          <h2 className="text-[10px] uppercase tracking-widest text-slate-400 font-mono flex items-center gap-2">
            <Compass className="w-3.5 h-3.5" /> 星系勘探仪 / EX-RADAR
          </h2>
          <div className="text-[10px] font-mono text-slate-500">
            质量评定: <span className="text-slate-300">{studentData.totalScore}</span>
          </div>
        </div>
        
        <div className="relative flex items-center justify-center mb-5 mt-2">
          {/* Animated SVG Ring */}
          <svg className={`w-36 h-36 transform -rotate-90 ${glowShadow}`} viewBox="0 0 120 120">
            {/* Background ring */}
            <circle
              cx="60"
              cy="60"
              r={radius}
              stroke="currentColor"
              strokeWidth="6"
              fill="transparent"
              className="text-white/5"
            />
            {/* Progress ring */}
            <motion.circle
              cx="60"
              cy="60"
              r={radius}
              stroke="currentColor"
              strokeWidth="6"
              fill="transparent"
              strokeLinecap="round"
              className={ringColor}
              strokeDasharray={circumference}
              initial={{ strokeDashoffset: circumference }}
              animate={{ strokeDashoffset }}
              transition={{ duration: 1.5, ease: "easeOut" }}
            />
          </svg>
          
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-[10px] text-slate-400 tracking-wider font-mono mb-0.5 mt-2">探索度</span>
            <div className={`text-4xl font-light tracking-tighter font-mono ${radarColor}`}>
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                key={explorationDegree}
              >
                {explorationDegree}
              </motion.span>
              <span className="text-xl opacity-60 ml-0.5">%</span>
            </div>
          </div>
        </div>

        {/* Small stats row */}
        <div className="w-full flex justify-between items-center px-2 pt-3 border-t border-white/5">
          <div className="flex flex-col items-center">
            <span className="text-[9px] text-slate-500 font-mono uppercase">已点亮星辰</span>
            <span className="text-xs text-slate-200 font-mono mt-1">{submittedAssignments.length} <span className="text-slate-500">/ {visibleAssignments.length}</span></span>
          </div>
          <div className="w-[1px] h-6 bg-white/10"></div>
          <div className="flex flex-col items-center">
            <span className="text-[9px] text-slate-500 font-mono uppercase">主星捕获 (AoL)</span>
            <span className={`text-xs font-mono mt-1 ${capturedAols === visibleAols.length ? radarColor : 'text-slate-200'}`}>
              {capturedAols} <span className="text-slate-500">/ {totalAoLs}</span>
            </span>
          </div>
        </div>
      </div>

      {/* 3. Captain's Log Memo Timeline (Replacing Badges grid) */}
      <div className="backdrop-blur-md bg-white/5 border border-white/10 rounded-2xl shadow-2xl flex-1 flex flex-col overflow-hidden">
        <div className="p-4 pb-3 border-b border-white/5 bg-white/[0.02]">
          <h2 className="text-[10px] uppercase tracking-widest text-slate-400 font-mono flex items-center gap-2">
            <History className="w-3.5 h-3.5" /> 航行日志 / Captain's Log
          </h2>
        </div>
        
        <div className="flex-1 overflow-y-auto p-4 space-y-5 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
          <AnimatePresence>
            {memos.length === 0 ? (
              <motion.div 
                initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                className="h-full flex items-center justify-center text-xs text-slate-500 font-mono text-center px-4 leading-relaxed"
              >
                暂无航行记录。<br/>请在右侧控制台输入战术规划。
              </motion.div>
            ) : (
              memos.map((memo, idx) => (
                <motion.div 
                  key={memo.id}
                  initial={{ opacity: 0, x: -20, height: 0 }}
                  animate={{ opacity: 1, x: 0, height: 'auto' }}
                  transition={{ duration: 0.4, delay: idx * 0.05 }}
                  className="relative pl-4"
                >
                  {/* Timeline logic */}
                  <div className="absolute left-0 top-1.5 bottom-[-24px] w-px bg-white/10 last:bottom-0"></div>
                  <div className={`absolute left-[-3.5px] top-1.5 w-2 h-2 rounded-full border border-[rgba(30,41,59,1)] ${idx === 0 ? radarBg : 'bg-slate-600'}`}></div>
                  
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-[10px] font-mono text-slate-400">{memo.phaseTitle}</span>
                    <span className="text-[9px] font-mono text-slate-600">
                      {new Date(memo.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                    </span>
                  </div>
                  <div className="text-[11px] text-emerald-50/80 leading-relaxed bg-white/[0.03] border border-white/5 rounded-lg p-2.5">
                    {memo.text}
                  </div>
                </motion.div>
              ))
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}
