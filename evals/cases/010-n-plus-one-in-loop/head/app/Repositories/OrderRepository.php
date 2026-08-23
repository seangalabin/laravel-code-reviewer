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

    public function summariseForDispatch(int $limit): array
    {
        $summaries = [];

        foreach ($this->findRecent($limit) as $order) {
            $summaries[] = [
                'reference' => $order->reference,
                'customer'  => $order->customer->name,
                'lines'     => $order->items->count(),
            ];
        }

        return $summaries;
    }
}
