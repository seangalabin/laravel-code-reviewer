<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\Invoice;
use App\Models\User;

final class InvoiceRepository
{
    public function find(int $invoiceId): ?Invoice
    {
        return Invoice::query()->find($invoiceId);
    }
}
