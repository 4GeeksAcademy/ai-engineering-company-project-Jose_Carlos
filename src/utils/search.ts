export type Comparable = number | string | Date

export function linealSearch<T>(arr: readonly T[], objetivo: T): number {
	for (let i = 0; i < arr.length; i++) {
		const elemento = arr[i]
		const coincide =
			elemento instanceof Date && objetivo instanceof Date
				? elemento.getTime() === objetivo.getTime()
				: elemento === objetivo

		if (coincide) {
			return i
		}
	}

	return -1
}

function compareComparable(a: Comparable, b: Comparable): number {
	const left = a instanceof Date ? a.getTime() : a
	const right = b instanceof Date ? b.getTime() : b

	if (left === right) {
		return 0
	}

	return left < right ? -1 : 1
}

export function binarySearch<T extends Comparable>(arr: readonly T[], objetivo: T): number {
	let low = 0
	let high = arr.length - 1

	while (low <= high) {
		const mid = Math.floor((low + high) / 2)
		const comparison = compareComparable(arr[mid], objetivo)

		if (comparison === 0) {
			return mid
		}

		if (comparison < 0) {
			low = mid + 1
		} else {
			high = mid - 1
		}
	}

	return -1
}