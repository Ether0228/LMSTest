import { create } from 'zustand';

export interface Memo {
  id: string;
  text: string;
  timestamp: number;
  phaseTitle: string;
}

interface AppState {
  radarState: 'idle' | 'scanning' | 'hovered' | 'locked';
  setRadarState: (state: 'idle' | 'scanning' | 'hovered' | 'locked') => void;
  memos: Memo[];
  addMemo: (text: string, phaseTitle: string) => void;
}

export const useStore = create<AppState>((set) => ({
  radarState: 'idle',
  setRadarState: (state) => set({ radarState: state }),
  memos: [
    {
      id: 'mock-1',
      text: '刚降落在这个星系，周围有点暗，需要先连续点亮3颗最小的星星建立稳定航线。',
      timestamp: Date.now() - 1000 * 60 * 60 * 24 * 5, // 5 days ago
      phaseTitle: 'Phase 1 - 刚刚落地'
    }
  ],
  addMemo: (text, phaseTitle) => set((state) => ({
    memos: [{
      id: Date.now().toString(),
      text,
      timestamp: Date.now(),
      phaseTitle
    }, ...state.memos]
  }))
}));
