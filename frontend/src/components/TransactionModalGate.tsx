import { lazy, Suspense } from 'react';
import { useTransactionComposer } from '@/hooks/useTransactionComposer';

const TransactionModal = lazy(() => import('./TransactionModal'));

export default function TransactionModalGate() {
  const { isOpen } = useTransactionComposer();

  if (!isOpen) {
    return null;
  }

  return (
    <Suspense fallback={null}>
      <TransactionModal />
    </Suspense>
  );
}
