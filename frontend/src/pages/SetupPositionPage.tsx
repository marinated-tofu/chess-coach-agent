import { useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { MessageCircle, Microscope } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { BoardEditor } from '../components/BoardEditor';
import { ImageToBoard } from '../components/ImageToBoard';
import { START_FEN, positionError } from '../lib/positionSetup';
import type { VisionResult } from '../lib/visionApi';
import './SetupPositionPage.css';

export function SetupPositionPage() {
  const navigate = useNavigate();
  const [fen, setFen] = useState(START_FEN);
  const [orientation, setOrientation] = useState<'white' | 'black'>('white');
  const error = positionError(fen);

  function loadResult(result: VisionResult) {
    setFen(result.fen);
    // Show the board the way it looked in the image so squares are easy to compare.
    setOrientation(result.orientation === 'black_at_bottom' ? 'black' : 'white');
  }

  function openAnalysis() {
    void navigate({ to: '/analysis', search: { fen } });
  }

  return (
    <main className="route-page setup-page">
      <PageHeader
        eyebrow="Set up position"
        title="From a picture or by hand"
        detail="Read a board from a screenshot or photo, fix anything it got wrong, then analyse it or ask the coach."
      />
      <div className="setup-layout">
        <div className="setup-card setup-editor">
          <BoardEditor fen={fen} onChange={setFen} orientation={orientation} onOrientationChange={setOrientation} />
        </div>
        <div className="setup-card setup-image">
          <ImageToBoard onResult={loadResult} />
        </div>
        <div className="setup-card setup-go">
          <button type="button" className="primary" disabled={Boolean(error)} onClick={openAnalysis}>
            <Microscope size={17} aria-hidden /> Open in analysis board
          </button>
          <button type="button" className="secondary" disabled={Boolean(error)} onClick={openAnalysis}>
            <MessageCircle size={17} aria-hidden /> Ask the coach
          </button>
          {error && <p className="setup-blocked">Fix the position first: {error}</p>}
        </div>
      </div>
    </main>
  );
}
