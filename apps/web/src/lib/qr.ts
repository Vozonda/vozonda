// QR codes for links the user moves to another device (the private feed link to a phone).
// qrcode-generator (MIT, Kazuhiko Arase) renders locally; no service sees the link, which carries a key.
import qrcode from 'qrcode-generator'

const escapeAttr = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** An inline SVG QR code for `text` (error correction M, readable from a screen), sized by CSS and
 *  labelled for screen readers. */
export function qrSvg(text: string, label = 'QR code'): string {
  const qr = qrcode(0, 'M')
  qr.addData(text)
  qr.make()
  return qr
    .createSvgTag({ cellSize: 4, margin: 2, scalable: true })
    .replace('<svg ', `<svg aria-label="${escapeAttr(label)}" `)
}
