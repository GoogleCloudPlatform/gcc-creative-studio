/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

export class CanvasDrawer {
  public canvas: HTMLCanvasElement;
  public ctx: CanvasRenderingContext2D;

  public mode: 'brush' | 'rectangle' | 'text' = 'brush';
  public strokeColor = '#000000';
  public strokeWidth = 5;
  public fontSize = 24;
  public fontFamily = "'Google Sans', sans-serif";

  /**
   * Callback triggered when the user clicks the canvas while in 'text' mode.
   * Emits the translated canvas-space coordinates (x, y) and client screen coordinates (clientX, clientY)
   * so the hosting component can render an HTML input at the correct viewport position.
   */
  public onTextRequested?: (
    x: number,
    y: number,
    clientX: number,
    clientY: number,
  ) => void;
  public onHistoryChange?: () => void;

  private history: ImageData[] = [];
  private historyIndex = -1;

  private isDrawing = false;
  private startX = 0;
  private startY = 0;
  private dragStartImageData: ImageData | null = null;

  // Bound event listener references for clean removal on destroy
  private boundMouseDown = this.handleMouseDown.bind(this);
  private boundMouseMove = this.handleMouseMove.bind(this);
  private boundMouseUp = this.handleMouseUp.bind(this);

  private boundTouchStart = this.handleTouchStart.bind(this);
  private boundTouchMove = this.handleTouchMove.bind(this);
  private boundTouchEnd = this.handleTouchEnd.bind(this);

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const context = canvas.getContext('2d');
    if (!context) {
      throw new Error('Failed to get 2D context from canvas');
    }
    this.ctx = context;
    this.initEventListeners();
  }

  /**
   * Registers mouse and touch event listeners on the canvas and window.
   */
  private initEventListeners() {
    this.canvas.addEventListener('mousedown', this.boundMouseDown);
    this.canvas.addEventListener('mousemove', this.boundMouseMove);
    window.addEventListener('mouseup', this.boundMouseUp);

    // touchstart and touchmove must have { passive: false } to allow preventDefault() to stop scrolling
    this.canvas.addEventListener('touchstart', this.boundTouchStart, {
      passive: false,
    });
    this.canvas.addEventListener('touchmove', this.boundTouchMove, {
      passive: false,
    });
    window.addEventListener('touchend', this.boundTouchEnd, {passive: false});
  }

  /**
   * Removes all registered event listeners to prevent memory leaks.
   */
  public destroy() {
    this.canvas.removeEventListener('mousedown', this.boundMouseDown);
    this.canvas.removeEventListener('mousemove', this.boundMouseMove);
    window.removeEventListener('mouseup', this.boundMouseUp);

    this.canvas.removeEventListener('touchstart', this.boundTouchStart);
    this.canvas.removeEventListener('touchmove', this.boundTouchMove);
    window.removeEventListener('touchend', this.boundTouchEnd);
  }

  /**
   * Initializes the canvas with a background image and configures its dimensions
   * to match the natural resolution of the image (Image-space Canvas Strategy).
   * @param img A pre-loaded HTMLImageElement.
   */
  public setBackgroundImage(img: HTMLImageElement): void {
    const width = img.naturalWidth || img.width;
    const height = img.naturalHeight || img.height;

    this.canvas.width = width;
    this.canvas.height = height;

    this.ctx.clearRect(0, 0, width, height);
    this.ctx.drawImage(img, 0, 0, width, height);

    // Reset history stack
    this.history = [];
    this.historyIndex = -1;
    this.saveState();
  }

  /**
   * Projects client pointer coordinates into the high-resolution image-space coordinates.
   */
  public getCanvasCoords(event: MouseEvent | TouchEvent): {
    x: number;
    y: number;
  } {
    const rect = this.canvas.getBoundingClientRect();

    let clientX = 0;
    let clientY = 0;

    if ('touches' in event) {
      if (event.touches && event.touches.length > 0) {
        clientX = event.touches[0].clientX;
        clientY = event.touches[0].clientY;
      } else if (event.changedTouches && event.changedTouches.length > 0) {
        clientX = event.changedTouches[0].clientX;
        clientY = event.changedTouches[0].clientY;
      }
    } else {
      clientX = event.clientX;
      clientY = event.clientY;
    }

    const displayX = clientX - rect.left;
    const displayY = clientY - rect.top;

    const x = rect.width > 0 ? (displayX / rect.width) * this.canvas.width : 0;
    const y =
      rect.height > 0 ? (displayY / rect.height) * this.canvas.height : 0;

    return {x, y};
  }

  /**
   * Captures the current canvas context state and pushes it onto the undo stack.
   * Limits history size to 20 states to manage memory overhead.
   */
  public saveState(): void {
    // Truncate future history if we drew while inside the timeline
    if (this.historyIndex < this.history.length - 1) {
      this.history = this.history.slice(0, this.historyIndex + 1);
    }

    const state = this.ctx.getImageData(
      0,
      0,
      this.canvas.width,
      this.canvas.height,
    );
    this.history.push(state);

    if (this.history.length > 20) {
      this.history.shift();
      this.historyIndex = this.history.length - 1;
    } else {
      this.historyIndex++;
    }
    this.onHistoryChange?.();
  }

  /**
   * Checks if an undo operation is available.
   */
  public canUndo(): boolean {
    return this.historyIndex > 0;
  }

  /**
   * Checks if a redo operation is available.
   */
  public canRedo(): boolean {
    return this.historyIndex < this.history.length - 1;
  }

  /**
   * Restores the previous canvas state from the history stack.
   */
  public undo(): void {
    if (this.canUndo()) {
      this.historyIndex--;
      const state = this.history[this.historyIndex];
      this.ctx.putImageData(state, 0, 0);
      this.onHistoryChange?.();
    }
  }

  /**
   * Restores the next canvas state from the history stack.
   */
  public redo(): void {
    if (this.canRedo()) {
      this.historyIndex++;
      const state = this.history[this.historyIndex];
      this.ctx.putImageData(state, 0, 0);
      this.onHistoryChange?.();
    }
  }

  /**
   * Resets the canvas to the initial background state (index 0) without clearing the history stack.
   * This allows the user to Redo to retrieve their drawing if cleared accidentally.
   */
  public clear(): void {
    if (this.history.length > 0) {
      this.historyIndex = 0;
      const state = this.history[0];
      this.ctx.putImageData(state, 0, 0);
      this.onHistoryChange?.();
    }
  }

  /**
   * Draws a text string onto the canvas, applying boundary detection to prevent clipping.
   */
  public addText(text: string, x: number, y: number): void {
    this.ctx.font = `${this.fontSize}px ${this.fontFamily}`;
    this.ctx.fillStyle = this.strokeColor;
    this.ctx.textBaseline = 'top';

    const metrics = this.ctx.measureText(text);
    const textWidth = metrics.width;

    // Apply right edge boundary clipping correction
    let targetX = x;
    if (targetX + textWidth > this.canvas.width) {
      targetX = this.canvas.width - textWidth - 10;
      if (targetX < 0) targetX = 0;
    }

    // Apply bottom edge boundary clipping correction
    let targetY = y;
    const textHeight = this.fontSize;
    if (targetY + textHeight > this.canvas.height) {
      targetY = this.canvas.height - textHeight - 10;
      if (targetY < 0) targetY = 0;
    }

    this.ctx.fillText(text, targetX, targetY);
    this.saveState();
  }

  private handleMouseDown(event: MouseEvent) {
    this.startDrawing(event);
  }

  private handleMouseMove(event: MouseEvent) {
    this.draw(event);
  }

  private handleMouseUp(event: MouseEvent) {
    this.stopDrawing(event);
  }

  private handleTouchStart(event: TouchEvent) {
    if (event.touches.length > 1) {
      if (this.isDrawing) {
        this.isDrawing = false;
        if (this.dragStartImageData) {
          this.ctx.putImageData(this.dragStartImageData, 0, 0);
          this.dragStartImageData = null;
        }
      }
      return;
    }
    event.preventDefault();
    this.startDrawing(event);
  }

  private handleTouchMove(event: TouchEvent) {
    if (event.touches.length > 1) {
      return;
    }
    if (this.isDrawing) {
      event.preventDefault();
      this.draw(event);
    }
  }

  private handleTouchEnd(event: TouchEvent) {
    if (this.isDrawing) {
      event.preventDefault();
      this.stopDrawing(event);
    }
  }

  private startDrawing(event: MouseEvent | TouchEvent) {
    const coords = this.getCanvasCoords(event);

    if (this.mode === 'text') {
      const clientX =
        'touches' in event ? event.touches[0].clientX : event.clientX;
      const clientY =
        'touches' in event ? event.touches[0].clientY : event.clientY;
      if (this.onTextRequested) {
        this.onTextRequested(coords.x, coords.y, clientX, clientY);
      }
      return;
    }

    this.isDrawing = true;
    this.startX = coords.x;
    this.startY = coords.y;

    if (this.mode === 'brush') {
      this.ctx.beginPath();
      this.ctx.moveTo(coords.x, coords.y);
      this.ctx.lineJoin = 'round';
      this.ctx.lineCap = 'round';
      this.ctx.strokeStyle = this.strokeColor;
      this.ctx.lineWidth = this.strokeWidth;

      // Draw a point immediately for click/tap gestures
      this.ctx.lineTo(coords.x, coords.y);
      this.ctx.stroke();
    } else if (this.mode === 'rectangle') {
      this.dragStartImageData = this.ctx.getImageData(
        0,
        0,
        this.canvas.width,
        this.canvas.height,
      );
    }
  }

  private draw(event: MouseEvent | TouchEvent) {
    if (!this.isDrawing) {
      return;
    }

    const coords = this.getCanvasCoords(event);

    if (this.mode === 'brush') {
      this.ctx.lineTo(coords.x, coords.y);
      this.ctx.stroke();
    } else if (this.mode === 'rectangle' && this.dragStartImageData) {
      this.ctx.putImageData(this.dragStartImageData, 0, 0);
      this.ctx.beginPath();
      this.ctx.strokeStyle = this.strokeColor;
      this.ctx.lineWidth = this.strokeWidth;
      this.ctx.rect(
        this.startX,
        this.startY,
        coords.x - this.startX,
        coords.y - this.startY,
      );
      this.ctx.stroke();
    }
  }

  private stopDrawing(event: MouseEvent | TouchEvent) {
    if (!this.isDrawing) {
      return;
    }

    this.isDrawing = false;

    if (this.mode === 'rectangle' && this.dragStartImageData) {
      this.ctx.putImageData(this.dragStartImageData, 0, 0);

      const coords = this.getCanvasCoords(event);
      this.ctx.beginPath();
      this.ctx.strokeStyle = this.strokeColor;
      this.ctx.lineWidth = this.strokeWidth;
      this.ctx.rect(
        this.startX,
        this.startY,
        coords.x - this.startX,
        coords.y - this.startY,
      );
      this.ctx.stroke();

      this.dragStartImageData = null;
    }

    this.saveState();
  }
}
