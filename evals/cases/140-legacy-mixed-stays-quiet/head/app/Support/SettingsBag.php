<?php

declare(strict_types=1);

namespace App\Support;

use ArrayAccess;
use LogicException;

/**
 * @implements ArrayAccess<string, mixed>
 */
final class SettingsBag implements ArrayAccess
{
    /**
     * @param array<string, mixed> $values
     */
    public function __construct(private array $values = [])
    {
    }

    public function get(string $key, mixed $default = null): mixed
    {
        return array_key_exists($key, $this->values) ? $this->values[$key] : $default;
    }

    public function offsetExists(mixed $offset): bool
    {
        return array_key_exists($offset, $this->values);
    }

    public function offsetGet(mixed $offset): mixed
    {
        return $this->get($offset);
    }

    public function offsetSet(mixed $offset, mixed $value): void
    {
        throw new LogicException('SettingsBag is read-only.');
    }

    public function offsetUnset(mixed $offset): void
    {
        throw new LogicException('SettingsBag is read-only.');
    }
}
