/** Board recognition from an image (backend: vision_api.py). */

export type VisionResult = {
  fen: string;
  side_to_move_guess: 'white' | 'black';
  confidence: number;
  warnings: string[];
  board_ascii: string;
  valid: boolean;
  orientation: 'white_at_bottom' | 'black_at_bottom';
  attempts: number;
  input_tokens: number;
  output_tokens: number;
  model: string;
  duration_ms: number;
};

export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

export async function readBoardImage(file: Blob, signal?: AbortSignal): Promise<VisionResult> {
  const form = new FormData();
  form.append('image', file, file instanceof File ? file.name : 'board.png');
  const response = await fetch('/api/vision/fen', { method: 'POST', body: form, signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Board reading failed (${response.status})`);
  }
  return response.json();
}
