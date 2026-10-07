import { readFileSync } from 'fs'
import { join } from 'path'

const root = join(__dirname, '..', 'src')

function readComponent(name: string): string {
  return readFileSync(join(root, 'lib', 'components', `${name}.svelte`), 'utf-8')
}

function readDesign(): string {
  return readFileSync(join(__dirname, '..', '..', '..', 'docs', 'design.md'), 'utf-8')
}

describe('UI Spinner & Cancel (VOZONDA-UI-CLI-SPINNER-CANCEL)', () => {
  const checklist = readComponent('PipelineChecklist')
  const queueIndicator = readComponent('QueueIndicator')
  const design = readDesign()

  describe('PipelineChecklist.svelte', () => {
    test('has no static ● for running state', () => {
      expect(checklist).not.toMatch(/mark\[.*running.*\].*[●•]/)
      expect(checklist).not.toMatch(/running:.*['"]●['"]/)
    })

    test('running mark is empty string', () => {
      expect(checklist).toMatch(/running:\s*['"]['"]/)
    })

    test('contains 10 braille frames in CSS ::before content', () => {
      const frames = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
      expect(checklist).toContain(frames)
    })

    test('spinner animation uses CSS @keyframes with steps()', () => {
      expect(checklist).toMatch(/@keyframes\s+braille-spin/)
      expect(checklist).toMatch(/steps\(10\)/)
    })

    test('prefers-reduced-motion rule exists for spinner', () => {
      expect(checklist).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/)
      expect(checklist).toMatch(/\.spinner\s*\{[^}]*animation:\s*none/)
      expect(checklist).toMatch(/\.spinner::before\s*\{[^}]*content:\s*["']▸["']/)
    })

    test('no setInterval or setTimeout in component', () => {
      expect(checklist).not.toContain('setInterval')
      expect(checklist).not.toContain('setTimeout')
    })

    test('spinner glyph is aria-hidden', () => {
      expect(checklist).toMatch(/<span class="spinner" aria-hidden="true"><\/span>/)
    })

    test('spinner uses mono font via inherited font-family', () => {
      expect(checklist).toMatch(/\.spinner\s*\{[^}]*font-family:\s*inherit/)
    })
  })

  describe('QueueIndicator.svelte', () => {
    test('has cancel button for queued jobs', () => {
      expect(queueIndicator).toMatch(/class="qi-cancel mono"/)
      expect(queueIndicator).toMatch(/onclick=\{requestCancel\}/)
    })

    test('has cancel button for running jobs', () => {
      expect(queueIndicator).toMatch(/{#if isRunning}.*class="qi-cancel mono"/s)
    })

    test('cancel button has aria-label with job title', () => {
      expect(queueIndicator).toMatch(/aria-label=\{`Cancel ".*\$\{jobTitle\}"/)
    })

    test('cancel button disabled while request in flight', () => {
      expect(queueIndicator).toMatch(/disabled=\{cancelPending\}/)
    })

    test('inline confirm for running jobs with voice stage started', () => {
      expect(queueIndicator).toMatch(/cancelConfirm && voiceStageStarted/)
      expect(queueIndicator).toMatch(/cancel render\?/)
      expect(queueIndicator).toMatch(/yes.*no/)
    })

    test('no confirmation for queued jobs', () => {
      expect(queueIndicator).toMatch(/if \(isQueued \|\| !voiceStageStarted\)/)
      expect(queueIndicator).toMatch(/cancelConfirm = false/)
    })

    test('calls onCancel callback with jobId', () => {
      expect(queueIndicator).toMatch(/await onCancel\(jobId\)/)
    })
  })

  describe('docs/design.md Motion section', () => {
    test('mentions CSS-only braille terminal spinner', () => {
      expect(design).toMatch(/CSS-only braille terminal spinner/)
    })

    test('mentions operator decision 2026-10-01', () => {
      expect(design).toMatch(/operator decision 2026-10-01/)
    })

    test('mentions prefers-reduced-motion static fallback', () => {
      expect(design).toMatch(/static under.*prefers-reduced-motion/)
    })

    test('mentions exception to nothing else moves', () => {
      expect(design).toMatch(/exception to.*nothing else moves/)
    })
  })
})