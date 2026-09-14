<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\Invoice;
use App\Models\User;
use Illuminate\Database\Eloquent\Collection;

final class InvoiceRepository
{
    public function find(int $invoiceId): ?Invoice
    {
        return Invoice::query()->find($invoiceId);
    }

    public function openForUser(User $user): Collection
    {
        return $user->invoices()
            ->where('status', 'open')
            ->orderByDesc('issued_at')
            ->get();
    }
}
