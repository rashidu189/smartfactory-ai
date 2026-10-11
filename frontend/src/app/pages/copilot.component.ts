import { AfterViewChecked, Component, ElementRef, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import { ApiService } from '../core/api.service';
import { ApiError, ChatTurn } from '../core/models';
import { ChatEntry, StateService } from '../core/state.service';
import { openEvidence } from '../shared/cites.component';

interface Seg { t: 'text' | 'bold' | 'cite'; v: string; after?: string; }
interface Line { bullet: boolean; segs: Seg[]; }

@Component({
  selector: 'app-copilot',
  templateUrl: './copilot.component.html',
})
export class CopilotComponent implements AfterViewChecked {
  @ViewChild('log') log?: ElementRef<HTMLElement>;
  message = '';
  busy = false;
  private scrollPending = false;
  readonly suggestions = [
    'Which line needs attention first, and why?',
    'Which machines are likely to fail soon, and what are the warning signs?',
    'Where is the bottleneck next week, and can we meet ERP demand?',
    'Why did Line 03 drop, and when did it start?',
    'Draft a 5-point plan for tomorrow’s production meeting.',
  ];
  private parsed = new WeakMap<ChatEntry, Line[]>();

  constructor(public state: StateService, private api: ApiService, private router: Router) {}

  get chat(): ChatEntry[] { return this.state.chat; }

  send(text?: string): void {
    const msg = (text ?? this.message).trim();
    const d = this.state.dataset;
    if (!msg || this.busy) return;
    const history: ChatTurn[] = this.chat.filter((c) => !c.error).map((c) => ({ role: c.role, text: c.text }));
    this.chat.push({ role: 'user', text: msg });
    this.message = '';
    this.busy = true;
    this.scrollPending = true;
    this.api.copilot(d?.id ?? null, msg, history).subscribe({
      next: (r) => { this.chat.push({ role: 'model', text: r.answer, reply: r }); this.done(); },
      error: (e: ApiError) => { this.chat.push({ role: 'model', text: '', error: e.message }); this.done(); },
    });
  }

  clear(): void { this.state.chat = []; }

  lines(c: ChatEntry): Line[] {
    let l = this.parsed.get(c);
    if (!l) { l = parse(c.text); this.parsed.set(c, l); }
    return l;
  }

  openFinding(id: string): void { openEvidence(this.router, id); }

  isValid(c: ChatEntry, id: string): boolean { return !!c.reply?.cited_ids.includes(id); }

  ngAfterViewChecked(): void {
    if (this.scrollPending && this.log) {
      this.log.nativeElement.scrollTop = this.log.nativeElement.scrollHeight;
      this.scrollPending = false;
    }
  }

  private done(): void { this.busy = false; this.scrollPending = true; }
}

/** Minimal, safe rendering: bullets, **bold** and [F1]-style citations. No HTML injection. */
function parse(text: string): Line[] {
  return text.split('\n').filter((l, i, a) => l.trim() || (i > 0 && a[i - 1].trim())).map((raw) => {
    const m = raw.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    const body = m ? m[1] : raw;
    const segs: Seg[] = [];
    for (const part of body.split(/(\*\*[^*]+\*\*|\[[FAPVMB]\d{1,4}\](?:\s*\[[FAPVMB]\d{1,4}\])*)/)) {
      if (!part) continue;
      if (part.startsWith('**')) segs.push({ t: 'bold', v: part.slice(2, -2) });
      else if (/^\[[FAPVMB]\d/.test(part)) (part.match(/[FAPVMB]\d{1,4}/g) || []).forEach((id) => segs.push({ t: 'cite', v: id }));
      else {
        // Keep punctuation right after a citation on the same line as the chip.
        const prev = segs[segs.length - 1];
        const m2 = part.match(/^([.,;:!?)]+)(.*)$/s);
        if (prev?.t === 'cite' && m2) { prev.after = m2[1]; if (m2[2]) segs.push({ t: 'text', v: m2[2] }); }
        else segs.push({ t: 'text', v: part });
      }
    }
    return { bullet: !!m, segs };
  });
}
