import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TransactionModalGate from './TransactionModalGate';

const mockUseTransactionComposer = vi.fn();

vi.mock('@/hooks/useTransactionComposer', () => ({
  useTransactionComposer: () => mockUseTransactionComposer(),
}));

vi.mock('./TransactionModal', () => ({
  default: () => <div>Transaction modal content</div>,
}));

describe('TransactionModalGate', () => {
  beforeEach(() => {
    mockUseTransactionComposer.mockReset();
  });

  it('renders nothing while the composer is closed', () => {
    mockUseTransactionComposer.mockReturnValue({ isOpen: false });

    const { container } = render(<TransactionModalGate />);

    expect(container).toBeEmptyDOMElement();
  });

  it('lazy-loads the transaction modal when the composer opens', async () => {
    mockUseTransactionComposer.mockReturnValue({ isOpen: true });

    render(<TransactionModalGate />);

    expect(await screen.findByText('Transaction modal content')).toBeInTheDocument();
  });
});
