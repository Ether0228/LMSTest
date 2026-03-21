import { useState } from 'react';
import { motion } from 'framer-motion';
import { studentData, assignments } from '../../store/mockData';
import { Flame, Target, Rocket, AlertTriangle, ShieldAlert } from 'lucide-react';
import { useStore } from '../../store/useStore';
import type { DemoPhase } from '../../store/phaseModel';

export function RightPanel({ phase }: { phase: DemoPhase }) {
  const addMemo = useStore((state) => state.addMemo);
  const [inputText, setInputText] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  // --- Tactical Radar Data Processing ---
  const revealThreshold = Math.floor(assignments.length * phase.revealRatio);
  const visibleAssignments = assignments.filter((_, idx) => idx <= revealThreshold);
  const futureAssignments = assignments.filter((_, idx) => idx > revealThreshold);

  const criticalMissing = visibleAssignments.filter(a => a.type === 'AOL' && a.status === 'Missing');
  const dailyMissing = visibleAssignments.filter(a => a.type === 'Daily' && a.status === 'Missing');
  const upcomingAols = futureAssignments.filter(a => a.type === 'AOL').slice(0, 2); // Show next 2 max

  // --- Navigator Dynamic Prompt ---
  let navPrompt = '';
  if (criticalMissing.length > 0) {
    navPrompt = `核心告急！丢失 ${criticalMissing.length} 颗主星，建议本周优先执行 [CRITICAL] 拦截任务。`;
  } else if (dailyMissing.length >= 4) {
    navPrompt = `日常碎片遗落过多（${dailyMissing.length} 项），引擎输出受限。建议立刻开启一次集中清理。`;
  } else if (upcomingAols.length > 0) {
    navPrompt = `航向精准。前方不远处即将遭遇高维主星 [${upcomingAols[0].title}]，建议提前储备起跳能量。`;
  } else {
    navPrompt = `当前空域安全，探索度稳步提升中。请继续保持当前的提交频率，或休整飞船。`;
  }

  const handleSave = () => {
    if (!inputText.trim()) return;
    setIsSaving(true);
    setTimeout(() => {
      addMemo(inputText.trim(), phase.title);
      setInputText('');
      setIsSaving(false);
    }, 600);
  };

  return (
    <motion.div 
      initial={{ x: 50, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.8, ease: "easeOut", delay: 0.2 }}
      className="absolute right-8 top-8 bottom-24 w-80 z-10 flex flex-col gap-5 pointer-events-auto"
    >
      {/* 1. Streak Engine */}
      <div className="backdrop-blur-md bg-white/5 border border-white/10 rounded-2xl p-5 shadow-2xl relative overflow-hidden shrink-0 flex items-center justify-between">
        <div className="absolute top-0 right-0 w-32 h-32 bg-orange-500/10 rounded-full blur-2xl -translate-y-1/2 translate-x-1/2"></div>
        <div>
          <h2 className="text-[10px] uppercase tracking-widest text-slate-400 font-mono mb-2">跃迁引擎 / STREAK</h2>
          <div className="flex items-baseline gap-1">
            <span className="text-3xl font-mono text-white">{studentData.streak.current}</span>
            <span className="text-[10px] text-slate-500 font-mono uppercase">Days</span>
          </div>
        </div>
        <div className="text-right flex flex-col items-end">
          <div className="text-[10px] uppercase tracking-widest text-orange-400/80 font-mono mb-2 flex items-center gap-1">
            <Flame className="w-3 h-3" /> 历史极值
          </div>
          <div className="text-lg font-mono text-orange-200">
            {studentData.streak.highest} <span className="text-[10px] text-orange-500/60 uppercase">Days</span>
          </div>
        </div>
      </div>

      {/* 2. Tactical Radar */}
      <div className="backdrop-blur-md bg-white/5 border border-white/10 rounded-2xl p-5 shadow-2xl flex-1 flex flex-col overflow-hidden">
        <h2 className="text-[10px] uppercase tracking-widest text-emerald-400/80 font-mono mb-4 flex items-center gap-2 shrink-0">
          <Target className="w-3.5 h-3.5" /> 战术雷达 / TACTICAL
        </h2>

        <div className="flex-1 overflow-y-auto space-y-4 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent pr-2">
          
          {/* CRITICAL MISSING (AoLs) */}
          {criticalMissing.length > 0 && (
            <div className="border border-red-500/40 bg-red-900/15 rounded-xl p-3 relative overflow-hidden">
              <div className="absolute inset-0 pointer-events-none bg-[url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0IiBoZWlnaHQ9IjQiPgo8cmVjdCB3aWR0aD0iNCIgaGVpZ2h0PSI0IiBmaWxsPSJ0cmFuc3BhcmVudCIvPgo8cmVjdCB3aWR0aD0iNCIgaGVpZ2h0PSIxIiBmaWxsPSJyZ2JhKDI1NSwyNTUsMjU1LDAuMDUpIi8+Cjwvc3ZnPg==')] opacity-40 mix-blend-overlay"></div>
              <div className="text-[10px] font-bold tracking-widest text-red-400 mb-2 flex items-center gap-1.5 animate-pulse">
                <ShieldAlert className="w-3.5 h-3.5" /> [CRITICAL MISSING]
              </div>
              <div className="space-y-2">
                {criticalMissing.map(task => (
                  <div key={task.id} className="text-xs text-red-200/90 font-mono border-l-2 border-red-500/50 pl-2">
                    {task.title} <span className="text-[10px] text-red-400/60 ml-1">({task.dateStr})</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* UPCOMING AOLS */}
          {upcomingAols.length > 0 && (
            <div className="border border-amber-500/20 bg-amber-900/10 rounded-xl p-3">
              <div className="text-[10px] uppercase tracking-widest text-amber-400/80 mb-2 flex items-center gap-1.5">
                <Rocket className="w-3.5 h-3.5" /> 前方航线预警
              </div>
              <div className="space-y-2">
                {upcomingAols.map(task => (
                  <div key={task.id} className="text-xs text-amber-100/80 font-mono flex flex-col gap-0.5">
                    <span>{task.title}</span>
                    <span className="text-[10px] text-amber-500/60">预计抵达: {task.dateStr}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* DAILY MISSING */}
          {dailyMissing.length > 0 && (
            <div className="border border-white/10 bg-white/5 rounded-xl p-3">
              <div className="text-[10px] uppercase tracking-widest text-orange-400/70 mb-2 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" /> 碎片遗落
              </div>
              <div className="text-[11px] text-slate-300 leading-relaxed">
                星图检测到 <span className="text-orange-300 font-bold">{dailyMissing.length}</span> 处常规引力异常 (Daily Missing)。
                {dailyMissing.length > 3 && " 数量较多，建议本周抽空清理。"}
              </div>
            </div>
          )}

          {criticalMissing.length === 0 && dailyMissing.length === 0 && upcomingAols.length === 0 && (
            <div className="text-xs text-emerald-400/60 font-mono text-center py-6">
              雷达未见异常，航线畅通无阻。
            </div>
          )}
        </div>
      </div>

      {/* 3. Navigator Input */}
      <div className="backdrop-blur-md bg-[#0B0D14]/80 border border-emerald-500/20 rounded-2xl p-4 shadow-[0_0_20px_rgba(16,185,129,0.1)] shrink-0">
        <div className="text-[11px] leading-relaxed text-emerald-300/90 mb-3 border-l-2 border-emerald-500/40 pl-2">
          {navPrompt}
        </div>
        
        <div className="relative">
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            disabled={isSaving}
            className="w-full h-20 bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px] text-emerald-50 placeholder:text-emerald-500/30 resize-none focus:outline-none focus:border-emerald-500/50 transition-colors disabled:opacity-50 scrollbar-thin scrollbar-thumb-white/10"
            placeholder="[ 船长，请输入本周战术覆盖坐标 / Memo ]"
            spellCheck="false"
          />
        </div>
        
        <button
          onClick={handleSave}
          disabled={!inputText.trim() || isSaving}
          className={`mt-3 w-full py-2.5 rounded-lg text-[10px] uppercase tracking-widest font-bold transition-all ${
            inputText.trim() && !isSaving
              ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 hover:bg-emerald-500/30 shadow-[0_0_10px_rgba(16,185,129,0.2)]'
              : 'bg-white/5 text-slate-500 border border-white/5 cursor-not-allowed'
          }`}
        >
          {isSaving ? '正在注入航行日志...' : '执行航向 · Save'}
        </button>
      </div>
    </motion.div>
  );
}
