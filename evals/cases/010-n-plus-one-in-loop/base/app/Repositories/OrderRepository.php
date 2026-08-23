<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\Order;
use Illuminate\Support\Collection;

final class OrderRepository
{
    public function findRecent(int $limit): Collection
    {
        return Order::query()->latest()->limit($limit)->get();
    }
}
