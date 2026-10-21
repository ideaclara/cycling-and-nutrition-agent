import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Markdown } from './markdown';

describe('Markdown', () => {
  it('renders bold, numbered lists and paragraphs, and escapes HTML', () => {
    const { container } = render(
      <Markdown text={'**Today: amber.** Easy day.\n\n1. **Session.** 60 min\n2. Fuel <script>x</script>\n\nDone'} />,
    );
    expect(container.querySelectorAll('ol li')).toHaveLength(2);
    expect(container.querySelector('p strong')?.textContent).toBe('Today: amber.');
    expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toContain('<script>x</script>');
  });
});
